"""Persists Strands agent/swarm conversations that would otherwise be discarded.

Backs the knowledge-system backoffice (specs/plan-knowledge-backoffice.md). Every
function here owns its own AsyncSession (app.core.database.get_session_factory) and
commits independently of the caller's transaction — a run's trace must survive even
when the run itself fails and its own session gets rolled back (same isolation
rationale as KnowledgeAgentScheduler._run_step). Every function also swallows its own
exceptions: tracing is observability, never a dependency an agent run can fail on.

Connection independence note: in production this relies on the app's real
connection pool handing tracing's session a *different* physical connection than
the caller's — true for Postgres (AsyncAdaptedQueuePool, MVCC), which is what
guarantees a caller's later rollback can't undo a trace already committed here.
tests/conftest.py's in-memory SQLite engine uses StaticPool (SQLAlchemy's own
default for `sqlite+aiosqlite://` memory URLs) — a *single shared* connection for
every session in the whole test suite — so in tests, tracing's commit and the
caller's still-open transaction are, in effect, the same transaction. This is a
known test-harness limitation (see tests/unit/test_tracing.py's
TestSharedTestConnectionCaveat), not something production depends on: don't take
a passing test here as proof of cross-session isolation, and don't "fix" it by
asserting rollback-independence in a test against this engine.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.models.agent_run import AgentRun, RunStatus, RunTrigger, RunType
from app.models.agent_run_event import AgentRunEvent, RunEventType

logger = logging.getLogger(__name__)

TRACE_MAX_PAYLOAD_CHARS = 4000
_SUMMARY_MAX_CHARS = 20000


async def start_run(
    user_id: uuid.UUID,
    agent_key: str,
    run_type: RunType,
    trigger: RunTrigger,
    model_id: Optional[str] = None,
    parent_run_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Create the AgentRun row and return its id, or None if persisting fails.

    Never raises — callers pass the (possibly None) id straight through to
    finish_run/record_agent_events, which are themselves no-ops on None.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            run = AgentRun(
                user_id=user_id,
                agent_key=agent_key,
                run_type=run_type,
                trigger=trigger,
                model_id=model_id,
                parent_run_id=parent_run_id,
                status=RunStatus.RUNNING,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return run.id
    except Exception:
        logger.exception("tracing.start_run failed for agent_key=%s", agent_key)
        return None


async def finish_run(
    run_id: Optional[uuid.UUID],
    status: RunStatus,
    summary: Optional[str] = None,
    error: Optional[str] = None,
    stats: Optional[Dict[str, Any]] = None,
    usage_source: Any = None,
) -> None:
    """Close out an AgentRun with its final status, timing and token usage.

    usage_source is the raw object token usage gets pulled from — a Strands
    Agent (.event_loop_metrics.accumulated_usage), a SwarmResult
    (.accumulated_usage), a plain usage dict, or None — extracted by
    _extract_usage *inside* this function's own try/except. Earlier this took
    an already-extracted `usage` dict, computed by the caller via a getattr
    chain outside of any try/except — a lookup failure there (anything other
    than AttributeError, which getattr's default only catches) would have
    propagated out of this call and failed the agent run tracing is supposed
    to be transparent to.
    """
    if run_id is None:
        return
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            run = await db.get(AgentRun, run_id)
            if run is None:
                return
            now = datetime.now(timezone.utc)
            run.status = status
            run.finished_at = now
            started = run.started_at
            if started is not None:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                run.duration_ms = int((now - started).total_seconds() * 1000)
            if summary is not None:
                run.summary = summary[:_SUMMARY_MAX_CHARS]
            if error is not None:
                run.error = error[:_SUMMARY_MAX_CHARS]
            if stats is not None:
                run.stats = stats
            usage = _extract_usage(usage_source)
            if isinstance(usage, dict):
                run.input_tokens = _as_int(usage.get("inputTokens"))
                run.output_tokens = _as_int(usage.get("outputTokens"))
                run.total_tokens = _as_int(usage.get("totalTokens"))
            await db.commit()
    except Exception:
        logger.exception("tracing.finish_run failed for run_id=%s", run_id)


def _extract_usage(source: Any) -> Any:
    """Best-effort token usage extraction from a Strands Agent
    (.event_loop_metrics.accumulated_usage), a SwarmResult
    (.accumulated_usage), or a plain dict passed straight through.

    Deliberately swallows everything, not just AttributeError — called from
    inside finish_run's own try/except, but kept defensive on its own too
    since it's reachable from anywhere finish_run is.
    """
    try:
        if source is None or isinstance(source, dict):
            return source
        metrics = getattr(source, "event_loop_metrics", None)
        if metrics is not None:
            return getattr(metrics, "accumulated_usage", None)
        return getattr(source, "accumulated_usage", None)
    except Exception:
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def prune_traces(db: Any, user_id: uuid.UUID, retention_days: int) -> int:
    """Delete this user's AgentRun rows older than retention_days (their
    AgentRunEvent rows cascade via the FK's ON DELETE CASCADE — see
    alembic/versions/013_add_backoffice_tables.py). Returns the number of
    runs deleted, or 0 on failure — same "never raise" contract as the rest
    of this module, since a failed cleanup must not block the knowledge
    cycle step that calls it (see KnowledgeAgentScheduler._run_cycle).

    Uses the caller's own session/transaction rather than opening its own,
    unlike every other function here — this is a scheduled maintenance step
    invoked as its own KnowledgeAgentScheduler._run_step (which already
    provides a fresh session with per-step failure isolation), not something
    that needs to survive an unrelated run's rollback.
    """
    from sqlalchemy import delete

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        result = await db.execute(
            delete(AgentRun).where(AgentRun.user_id == user_id, AgentRun.started_at < cutoff)
        )
        return result.rowcount or 0
    except Exception:
        logger.exception("prune_traces failed for user=%s", user_id)
        return 0


async def record_agent_events(
    run_id: Optional[uuid.UUID],
    agent: Any,
    actor: Optional[str] = None,
) -> None:
    """Serialize one Agent's `.messages` into AgentRunEvent rows.

    Calling this more than once for the same run_id (e.g. once per swarm node
    in record_swarm_negotiation) won't collide on `seq` — the next value is
    read from the DB rather than tracked in memory — but it always
    re-serializes the *entire* messages list passed in from index 0. Only
    call it once per distinct Agent instance per run: every current call site
    does exactly that (one call per domain/orchestrator agent, one call per
    unique swarm node id via record_swarm_negotiation's seen_node_ids dedup).
    Calling it twice against the same still-growing `.messages` list would
    re-write already-recorded messages as duplicate rows — there's no
    high-water-mark to skip what a prior call already wrote.
    """
    if run_id is None:
        return
    try:
        messages = getattr(agent, "messages", None)
        events = _messages_to_events(messages if isinstance(messages, list) else [], actor=actor)
    except Exception:
        logger.exception("tracing.record_agent_events: failed to serialize messages for run_id=%s", run_id)
        return
    if not events:
        return
    await _write_events(run_id, events)


async def record_swarm_negotiation(run_id: Optional[uuid.UUID], swarm_result: Any) -> None:
    """Trace a completed Swarm negotiation: the handoff order, then each visited
    node's own conversation.

    swarm_result is a strands.multiagent.swarm.SwarmResult — duck-typed here (only
    `.node_history`, each a SwarmNode with `.node_id`/`.executor`) so this file
    doesn't import strands at module load time, matching every other agent factory
    in this codebase (strands_orchestrator.py, domain_agent.py) which imports it
    lazily inside functions.
    """
    if run_id is None:
        return
    node_history = getattr(swarm_result, "node_history", None)
    if not isinstance(node_history, list):
        # Not a real SwarmResult — e.g. a mocked Swarm in tests, or run_negotiation
        # returned None because the swarm itself crashed. Nothing to trace.
        return
    try:
        if len(node_history) > 1:
            handoff_events: List[Tuple[RunEventType, Optional[str], Optional[str], Dict[str, Any]]] = [
                (
                    RunEventType.HANDOFF,
                    node.node_id,
                    None,
                    {"to": node_history[i + 1].node_id},
                )
                for i, node in enumerate(node_history[:-1])
            ]
            await _write_events(run_id, handoff_events)

        seen_node_ids = set()
        for node in node_history:
            if node.node_id in seen_node_ids:
                continue
            seen_node_ids.add(node.node_id)
            await record_agent_events(run_id, node.executor, actor=node.node_id)
    except Exception:
        logger.exception("tracing.record_swarm_negotiation failed for run_id=%s", run_id)


async def record_verdict_event(
    run_id: Optional[uuid.UUID], actor: str, payload: Dict[str, Any],
) -> None:
    """Record the outcome closure callers pass to run_negotiation captures
    (e.g. submit_verdict's resolved/answer/confidence)."""
    if run_id is None:
        return
    await _write_events(run_id, [(RunEventType.VERDICT, actor, None, payload)])


async def record_error_event(run_id: Optional[uuid.UUID], actor: Optional[str], error: str) -> None:
    """Not called by any current run — every call site reports failure via
    finish_run's per-run `error` column instead. Reserved for a future
    finer-grained per-event error (e.g. a single tool call failing mid-run
    without ending the whole run), which isn't a scenario Phase 1 needs yet."""
    if run_id is None:
        return
    await _write_events(run_id, [(RunEventType.ERROR, actor, None, {"error": error})])


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _truncate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bound a JSONB payload's serialized size — tool results routinely carry
    whole source documents."""
    try:
        raw = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"unserializable": True}
    if len(raw) <= TRACE_MAX_PAYLOAD_CHARS:
        return payload
    return {"truncated": True, "preview": raw[:TRACE_MAX_PAYLOAD_CHARS]}


async def _write_events(
    run_id: uuid.UUID,
    events: Sequence[Tuple[RunEventType, Optional[str], Optional[str], Dict[str, Any]]],
) -> None:
    if not events:
        return
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            seq = await _next_seq(db, run_id)
            for event_type, actor, tool_name, payload in events:
                db.add(AgentRunEvent(
                    run_id=run_id,
                    seq=seq,
                    event_type=event_type,
                    actor=actor,
                    tool_name=tool_name,
                    payload=_truncate(payload),
                ))
                seq += 1
            await db.commit()
    except Exception:
        logger.exception("tracing: failed to write events for run_id=%s", run_id)


async def _next_seq(db: Any, run_id: uuid.UUID) -> int:
    result = await db.execute(select(func.max(AgentRunEvent.seq)).where(AgentRunEvent.run_id == run_id))
    current_max = result.scalar_one_or_none()
    return 0 if current_max is None else current_max + 1


def _messages_to_events(
    messages: List[Dict[str, Any]], actor: Optional[str],
) -> List[Tuple[RunEventType, Optional[str], Optional[str], Dict[str, Any]]]:
    """Turn a Strands agent's `.messages` (role + content blocks) into event tuples.

    Only assistant-authored blocks and tool results are kept — plain user-role text
    blocks are the task prompt the caller already knows, not agent output.
    """
    out: List[Tuple[RunEventType, Optional[str], Optional[str], Dict[str, Any]]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "")
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if "toolUse" in block:
                tool_use = block["toolUse"]
                out.append((
                    RunEventType.TOOL_CALL, actor, tool_use.get("name"),
                    {"tool_use_id": tool_use.get("toolUseId"), "input": tool_use.get("input")},
                ))
            elif "toolResult" in block:
                tool_result = block["toolResult"]
                out.append((
                    RunEventType.TOOL_RESULT, actor, None,
                    {
                        "tool_use_id": tool_result.get("toolUseId"),
                        "status": tool_result.get("status"),
                        "content": tool_result.get("content"),
                    },
                ))
            elif role == "assistant" and block.get("text"):
                out.append((RunEventType.ASSISTANT_TEXT, actor, None, {"text": block["text"]}))
    return out
