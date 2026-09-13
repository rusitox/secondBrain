"""Strands-based agent orchestrator — single-agent replacement for MultiAgentOrchestrator.

Uses AWS Strands Agents with an OpenAI-compatible model backend. All tools are
injected via ``make_agent_tools`` closures so the Strands Agent receives a
flat list of ready-to-call tool functions — no sub-agent parallelism required.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from importlib import metadata
from typing import (
    TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.stream import StreamEmitter
from app.models.conversation_turn import ConversationTurn
from app.services.agent import interactions_store

if TYPE_CHECKING:
    from strands.agent.agent_result import AgentResult
    from strands.types.content import Message

logger = logging.getLogger(__name__)

CONVERSATION_WINDOW = 20
SESSION_EXPIRY_HOURS = 24


class SnapshotUnavailableError(RuntimeError):
    """Raised by ``resume()`` when no live ``AgentSessionState`` exists for
    a session — expired, swept, or the session was never actually paused.

    The caller (``POST /interactions/{id}/answer``) turns this into a
    client-visible error rather than silently starting a fresh conversation
    from a synthesized prompt — that "orphan mode" fallback is real future
    work (see the plan's Fase 5 hardening) but a bigger behavior change than
    this phase takes on; failing clearly is the honest simpler behavior.
    """


def _installed_strands_version() -> str:
    try:
        return metadata.version("strands-agents")
    except metadata.PackageNotFoundError:
        return "unknown"

# Static tool -> thinking-panel category map. Deliberately code-owned and
# never model-chosen: the category drives a fixed badge color client-side,
# and letting the LLM pick it would mean trusting model output to pick from
# a UI vocabulary rather than the vocabulary constraining the model.
_TOOL_CATEGORY: Dict[str, str] = {
    "search_memory": "AGENTE",
    "query_knowledge": "AGENTE",
    "search_learnings": "AGENTE",
    "get_pending_questions": "AGENTE",
    "confirm_pending_answer": "AGENTE",
    "list_tasks": "HERRAMIENTA",
    "get_calendar": "HERRAMIENTA",
    "web_search": "HERRAMIENTA",
    "http_request": "HERRAMIENTA",
    "get_current_datetime": "HERRAMIENTA",
    "get_user_style": "SISTEMA",
    "get_sync_status": "SISTEMA",
    # SISTEMA, not HERRAMIENTA: writing to long-term memory is a system-
    # level action the same way get_sync_status/get_user_style are — the
    # thinking panel should read "the system remembered something" rather
    # than "a tool ran".
    "save_learning": "SISTEMA",
}
_DEFAULT_TOOL_CATEGORY = "HERRAMIENTA"

# Strands' own StopReason has 12 values (strands/types/event_loop.py):
# cancelled, checkpoint, content_filtered, end_turn, guardrail_intervened,
# interrupt, limit_output_tokens, limit_total_tokens, limit_turns,
# max_tokens, stop_sequence, tool_use. The done SSE event's contract (see
# app.api.schemas.stream.StopReason) only ever needs to distinguish three
# things: a clean completion, a deliberate pause for human input, or
# anything else — which the client always treats as an error state.
_UI_STOP_REASONS = frozenset({"end_turn", "interrupt"})


def _normalize_stop_reason(raw: str) -> str:
    """Map a raw Strands stop_reason onto the 3-value client contract.

    Anything Strands can produce that isn't a clean end or an interrupt —
    a token/turn limit, content filtering, cancellation, etc. — becomes
    "error" so a client only ever has to handle three cases; the raw value
    is still logged so the underlying reason isn't lost for diagnostics.
    """
    if raw in _UI_STOP_REASONS:
        return raw
    logger.warning("StrandsOrchestrator: unusual stop_reason=%s normalized to 'error'", raw)
    return "error"


def _parsed_json_block(block: Dict[str, Any]) -> Any:
    """A tool-result content block's structured payload, however Strands
    actually chose to carry it. Empirically, Strands' OpenAI provider wraps
    a `list`-returning tool's result as a real `{"json": [...]}` block, but
    a `dict`-returning tool's result (e.g. propose_action, whose payload is
    a single object) instead comes back as `{"text": "<json-encoded-str>"}`
    — a genuine asymmetry in Strands itself, not a formatting choice made
    here. Checking `json` first, falling back to parsing `text`, handles
    both without needing to know which one a given tool will get."""
    payload = block.get("json")
    if payload is not None:
        return payload
    text = block.get("text")
    if isinstance(text, str):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None
    return None


def _summarize_tool_result(tool_result: Dict[str, Any]) -> str:
    """Build a short, server-computed summary for a tool_result SSE event.

    Never forwards raw tool output: content blocks may carry ingested
    third-party text (email/Slack bodies), which shouldn't reach the client
    verbatim as a system-authored message.
    """
    if tool_result.get("status") != "success":
        return "error"
    content = tool_result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            payload = _parsed_json_block(block)
            if isinstance(payload, list):
                n = len(payload)
                return f"{n} resultado{'s' if n != 1 else ''}"
            if isinstance(payload, dict):
                return "completado"
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                first_line = text.strip().splitlines()[0]
                return (first_line[:80] + "…") if len(first_line) > 80 else first_line
    return "completado"


def _extract_proposed_action_id(tool_name: str, tool_result: Dict[str, Any]) -> Optional[str]:
    """If this tool_result is a propose_action call that produced a real
    action_id, pull it out — the only way the client learns the action
    exists at all (see ActionProposedEvent's docstring in
    app.api.schemas.stream). Reads the structured payload directly rather
    than parsing _summarize_tool_result's free-text summary, which is for
    display only.

    Deliberately accepts ANY status, not just "proposed": propose_action's
    idempotency path returns the SAME action_id with whatever its current
    status actually is (approved/executing/executed/...) when an
    identical payload is re-proposed while an earlier proposal is still in
    flight (strands_tools.py's idempotency-hit and race-fallback returns).
    Gatekeeping on status="proposed" here would silently drop those cases
    — the client's GET (app.api.routers.interactions.get_proposed_action)
    always returns the true current status anyway, so the frontend is
    what decides what's actionable, not this emission.
    """
    if tool_name != "propose_action" or tool_result.get("status") != "success":
        return None
    content = tool_result.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        payload = _parsed_json_block(block)
        if isinstance(payload, dict):
            action_id = payload.get("action_id")
            if isinstance(action_id, str):
                return action_id
    return None


# ---------------------------------------------------------------------------
# Streaming callback handler
# ---------------------------------------------------------------------------

class _StreamingCallbackHandler:
    """Strands callback handler — synchronously emits typed SSE events.

    Strands invokes this callback once per callback-eligible event (see
    ``strands/types/_events.py``): ``current_tool_use`` on tool start,
    a user-role ``message`` carrying ``toolResult`` blocks on tool
    completion (``ToolResultEvent`` itself is NOT a callback event — results
    only reach us via that message), ``reasoningText`` for extended
    thinking, and ``data`` for answer tokens.

    ``emit`` must be a plain synchronous callable. An earlier version
    scheduled ``stream_callback`` coroutines with a fire-and-forget
    ``loop.create_task(...)``: the task reference wasn't retained (so per
    the asyncio docs it could be garbage-collected mid-flight), emission
    order wasn't guaranteed once more than one event type existed, and
    exceptions were silently swallowed. Strands always invokes this handler
    synchronously from the same task that is iterating ``stream_async``, so
    a synchronous call is both correct and preserves order exactly.
    """

    def __init__(self, emit: Optional[StreamEmitter]) -> None:
        self._emit = emit
        self.tools_used: List[str] = []
        self._seen_tool_use_ids: set = set()
        self._tool_names: Dict[str, str] = {}
        self.iterations: int = 0
        self._reasoning_text: str = ""
        self._reasoning_active: bool = False

    def _emit_event(self, event: str, data: Dict[str, Any]) -> None:
        if self._emit is not None:
            self._emit(event, data)

    def _finish_reasoning_if_active(self) -> None:
        """Close the "reasoning" thinking row once something else starts.

        Strands has no terminal reasoning event — reasoning simply stops
        being followed by more reasoning deltas once the model moves on to
        a tool call or its final answer, so that's the signal we use here.
        The done emission carries the full accumulated text once (see
        ThinkingEvent's docstring for why): active emissions only ever sent
        deltas, to keep bytes transferred linear in reasoning length.
        """
        if self._reasoning_active:
            self._emit_event("thinking", {
                "id": "reasoning", "status": "done", "label": self._reasoning_text,
            })
            self._reasoning_active = False
            self._reasoning_text = ""

    def __call__(self, **kwargs: Any) -> None:
        """Receive a Strands callback event and translate it into SSE events."""
        # Reasoning text — checked first: it carries no "data" key, and
        # would otherwise fall through unnoticed. Strands delivers only the
        # incremental delta chunk here (see
        # strands/event_loop/streaming.py::_handle_content_block_delta,
        # `reasoning_text=delta_content["reasoningContent"]["text"]`). We
        # accumulate it for the terminal "done" emission (see
        # _finish_reasoning_if_active) but stream only the delta as `label`
        # on each "active" emission — resending the whole accumulated text
        # on every delta would make bytes transferred grow quadratically
        # with reasoning length. A client appends deltas for id="reasoning"
        # the same way it appends `token` events into the answer.
        reasoning_delta = kwargs.get("reasoningText")
        if kwargs.get("reasoning") and reasoning_delta:
            self._reasoning_text += reasoning_delta
            self._reasoning_active = True
            self._emit_event("thinking", {
                "id": "reasoning",
                "category": "RAZONAMIENTO",
                "label": reasoning_delta,
                "status": "active",
            })
            return

        # Tool call starting. Input streams incrementally as JSON, so this
        # fires repeatedly per call — dedupe on toolUseId to emit exactly
        # one "active" step.
        current_tool_use: Optional[Dict[str, Any]] = kwargs.get("current_tool_use")
        if current_tool_use:
            self._finish_reasoning_if_active()
            tool_use_id: str = current_tool_use.get("toolUseId", "")
            tool_name: str = current_tool_use.get("name", "")
            if tool_use_id and tool_use_id not in self._seen_tool_use_ids:
                self._seen_tool_use_ids.add(tool_use_id)
                self._tool_names[tool_use_id] = tool_name
                if tool_name and tool_name not in self.tools_used:
                    self.tools_used.append(tool_name)
                self.iterations += 1
                logger.debug("StrandsOrchestrator: tool called=%s", tool_name)
                self._emit_event("thinking", {
                    "id": tool_use_id,
                    "category": _TOOL_CATEGORY.get(tool_name, _DEFAULT_TOOL_CATEGORY),
                    "label": tool_name,
                    "status": "active",
                })

        # Tool result — delivered as a user-role Message whose content list
        # holds the toolResult blocks (ToolResultMessageEvent).
        message = kwargs.get("message")
        if isinstance(message, dict) and message.get("role") == "user":
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                tool_result = block.get("toolResult")
                if not isinstance(tool_result, dict):
                    continue
                tool_use_id = tool_result.get("toolUseId", "")
                ok = tool_result.get("status") == "success"
                tool_name = self._tool_names.get(tool_use_id, "")
                self._emit_event("tool_result", {
                    "id": tool_use_id,
                    "tool": tool_name,
                    "ok": ok,
                    "summary": _summarize_tool_result(tool_result),
                })
                self._emit_event("thinking", {
                    "id": tool_use_id,
                    "status": "done" if ok else "error",
                })
                proposed_action_id = _extract_proposed_action_id(tool_name, tool_result)
                if proposed_action_id is not None:
                    self._emit_event("action_proposed", {"id": proposed_action_id})

        # Text token — part of the final answer streaming to the client.
        data: str = kwargs.get("data", "")
        if data:
            self._finish_reasoning_if_active()
            self._emit_event("token", {"text": data})


# ---------------------------------------------------------------------------
# StrandsOrchestrator
# ---------------------------------------------------------------------------

class StrandsOrchestrator:
    """Single Strands Agent orchestrator with conversation persistence.

    Drop-in async replacement for ``MultiAgentOrchestrator``.  Builds a
    Strands ``Agent`` per request (stateless) so there are no concurrency
    issues with shared agent state.
    """

    def __init__(self, embedder: Optional[Any] = None) -> None:
        self._embedder = embedder

    async def query(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        question: str,
        session_id: Optional[str] = None,
        emit: Optional[StreamEmitter] = None,
    ) -> Dict[str, Any]:
        """Run a query through the Strands agent.

        Steps:
        1. Resolve/load conversation session from DB.
        2. Fetch user identity and communication style.
        3. Build system prompt incorporating identity, style, and date.
        4. Instantiate a Strands Agent with all tools.
        5. Run the agent (streaming if ``emit`` is provided).
        6. Persist conversation turns.
        7. Return structured result dict.

        Args:
            db: Async SQLAlchemy session for the current request.
            user_id: Authenticated user's UUID.
            question: Raw user question text.
            session_id: Existing session UUID string, or None to start fresh.
            emit: Synchronous ``(event_name, data) -> None`` callable for SSE
                streaming — see ``app.api.schemas.stream.StreamEmitter``. When
                provided, a ``session`` event is emitted immediately (before
                any token) so the client can route before generation starts.
                Pass None for non-streaming queries.

        Returns:
            Dict with keys: answer, tools_used, sources, session_id,
            iterations, turn_id, stop_reason, awaiting.
        """
        # 1. Resolve session and load history. Deliberately does not check
        # for an open UserInteraction/paused AgentSessionState on this
        # session first — a user who ignores a pending question and just
        # keeps talking should be able to (allow_dismiss exists precisely
        # for "not every question is mandatory"). The old interaction sits
        # unresolved until it expires (harmless) or is answered later, at
        # which point resume() replays it against its own pre-abandonment
        # snapshot — a natural conversation branch, not corruption.
        resolved_session_id, history = await self._resolve_session(db, user_id, session_id)
        session_uuid = uuid.UUID(resolved_session_id)
        turn_id = uuid.uuid4()

        if emit is not None:
            emit("session", {"session_id": resolved_session_id, "turn_id": str(turn_id)})

        # 2. Fetch user identity and style
        user_name, user_email, user_tz = await self._fetch_user_identity(db, user_id)
        style_info = await self._fetch_user_style(db, user_id)
        style_text = _format_style(style_info)

        # 3. Build system prompt
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system_prompt = _build_system_prompt(
            today_str=today_str,
            user_name=user_name,
            user_email=user_email,
            user_timezone=user_tz,
            style_text=style_text,
        )

        logger.info(
            "StrandsOrchestrator: starting query user=%s session=%s question=%r",
            user_id,
            resolved_session_id,
            question[:80],
        )

        # 4. Build Strands Agent
        agent = self._build_agent(
            db=db,
            user_id=user_id,
            user_tz=user_tz,
            system_prompt=system_prompt,
            history=history,
            emit=emit,
            session_id=session_uuid,
        )

        # 5. Run agent — capture the terminal AgentResult either way, instead
        # of reconstructing the answer from agent.messages, so stop_reason
        # and any interrupts are available.
        try:
            result = await self._run_agent(agent, question, emit)
        except Exception:
            logger.exception(
                "StrandsOrchestrator: agent failed for user=%s question=%r",
                user_id,
                question[:80],
            )
            raise

        # 6-7. Persist turns (branching on a clean end vs. a new interrupt)
        # and return the result dict.
        return await self._finalize_turn(db, user_id, session_uuid, turn_id, question, agent, result)

    async def resume(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        interrupt_id: str,
        answer_values: Dict[str, Any],
        emit: Optional[StreamEmitter] = None,
    ) -> Dict[str, Any]:
        """Resume a turn paused by request_user_input, replaying the human's
        answer into Strands' interrupt-response protocol.

        The caller (``POST /interactions/{id}/answer``) owns the
        UserInteraction's own status transition (open -> answered) and must
        have already claimed it before calling this — this method only
        knows how to resume Strands, not the interaction's lifecycle, so it
        does not re-check or care whether the interaction row exists.

        Raises:
            SnapshotUnavailableError: No live AgentSessionState for this
                session (expired, swept, or never actually paused).
        """
        turn_id = uuid.uuid4()
        session_id_str = str(session_id)

        if emit is not None:
            emit("session", {"session_id": session_id_str, "turn_id": str(turn_id)})

        session_state = await interactions_store.get_session_state(db, user_id, session_id)
        if session_state is None:
            raise SnapshotUnavailableError(f"no live agent session state for session_id={session_id}")
        expires_at = session_state.expires_at
        if expires_at.tzinfo is None:
            # SQLite (and some driver configs) return naive datetimes even
            # for a TIMESTAMP(timezone=True) column — normalize before
            # comparing, same reasoning as _resolve_session's expiry check.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise SnapshotUnavailableError(f"agent session state expired for session_id={session_id}")
        installed_version = _installed_strands_version()
        if session_state.strands_version != installed_version:
            # Snapshot.validate() only checks Strands' own schema_version
            # ("1.0"), which is unrelated to the SDK's package version — a
            # strands-agents upgrade can change internal message/tool-call
            # shape without bumping that. Discarding on any version drift
            # (not just major) is the conservative choice: a stale snapshot
            # deserializing "successfully" into a subtly wrong shape is
            # worse than a clean SnapshotUnavailableError.
            logger.warning(
                "StrandsOrchestrator: snapshot strands_version=%s != installed=%s for session_id=%s — discarding",
                session_state.strands_version, installed_version, session_id,
            )
            raise SnapshotUnavailableError(
                f"snapshot was captured with strands-agents={session_state.strands_version}, "
                f"installed={installed_version}"
            )

        user_name, user_email, user_tz = await self._fetch_user_identity(db, user_id)
        style_info = await self._fetch_user_style(db, user_id)
        style_text = _format_style(style_info)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system_prompt = _build_system_prompt(
            today_str=today_str,
            user_name=user_name,
            user_email=user_email,
            user_timezone=user_tz,
            style_text=style_text,
        )

        # history=[] deliberately — load_snapshot below overwrites
        # agent.messages entirely with the paused conversation's own
        # history (which already includes the dangling toolUse), so
        # pre-seeding it here would just be discarded.
        agent = self._build_agent(
            db=db, user_id=user_id, user_tz=user_tz, system_prompt=system_prompt, history=[], emit=emit,
            session_id=session_id,
        )

        from strands import Snapshot

        agent.load_snapshot(Snapshot.from_dict(session_state.snapshot))

        prompt = [{"interruptResponse": {"interruptId": interrupt_id, "response": answer_values}}]
        user_turn_content = "; ".join(f"{k}: {v}" for k, v in answer_values.items())

        logger.info(
            "StrandsOrchestrator: resuming session=%s interrupt=%s user=%s",
            session_id, interrupt_id, user_id,
        )

        try:
            result = await self._run_agent(agent, prompt, emit)
        except Exception:
            logger.exception(
                "StrandsOrchestrator: resume failed for user=%s session=%s interrupt=%s",
                user_id, session_id, interrupt_id,
            )
            raise

        return await self._finalize_turn(db, user_id, session_id, turn_id, user_turn_content, agent, result)

    # ------------------------------------------------------------------
    # Shared run/finalize logic (query() and resume())
    # ------------------------------------------------------------------

    async def _run_agent(self, agent: Any, prompt: Any, emit: Optional[StreamEmitter]) -> "AgentResult":
        """Drive a Strands Agent to completion and return its terminal
        AgentResult — shared by query() (a fresh text prompt) and resume()
        (interruptResponse content blocks); only ``prompt`` differs."""
        result: Optional["AgentResult"] = None
        if emit is not None:
            async for event in agent.stream_async(prompt):
                if "result" in event:
                    result = event["result"]
        else:
            result = await agent.invoke_async(prompt)

        if result is None:
            raise RuntimeError("Strands agent run produced no result")
        return result

    async def _finalize_turn(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        user_turn_content: str,
        agent: Any,
        result: "AgentResult",
    ) -> Dict[str, Any]:
        """Branch on whether the run ended cleanly or paused on a new
        interrupt, persisting the right rows either way, and build the
        result dict query()/resume() both return."""
        handler: _StreamingCallbackHandler = agent.callback_handler  # type: ignore[assignment]
        tools_used = handler.tools_used
        iterations = handler.iterations + 1  # +1 for the LLM synthesis turn
        session_id_str = str(session_id)

        parsed: List[Tuple[str, str, Dict[str, Any]]] = []
        if result.stop_reason == "interrupt" and result.interrupts:
            for interrupt in result.interrupts:
                reason = interrupt.reason if isinstance(interrupt.reason, dict) else {}
                ui_request = reason.get("ui_request")
                tool_use_id = reason.get("tool_use_id", "")
                if not isinstance(ui_request, dict):
                    logger.warning(
                        "StrandsOrchestrator: interrupt id=%s has no ui_request payload — skipping",
                        interrupt.id,
                    )
                    continue
                parsed.append((interrupt.id, tool_use_id, ui_request))

        if parsed:
            # AgentSessionState keeps only ONE snapshot row per session_id
            # (upsert_session_state) — so when a single LLM turn requests
            # several request_user_input calls at once, all of that
            # batch's interactions share that one row. Answering them
            # SEQUENTIALLY (one at a time, resuming, re-pausing on the
            # rest) works correctly: Strands' interrupt state is a dict
            # keyed by interrupt_id (strands/interrupt.py), so a partial
            # resume answering one sibling leaves the others' entries
            # untouched — they re-raise with the SAME interrupt_id, which
            # keep_interrupt_ids below protects from being swept, and
            # get_or_create_interaction reuses rather than re-inserting.
            # This is also the only path our own UI ever takes — ChatView
            # only ever shows pendingInteractionIds[0] as a modal, one at
            # a time, by design.
            #
            # Residual, narrower risk: answering two siblings via
            # genuinely CONCURRENT requests (bypassing the single-modal
            # UI — e.g. two browser tabs, or a non-UI client) still races:
            # both would load the same pre-split snapshot, and whichever
            # finalize_turn's upsert_session_state commits last silently
            # overwrites the other's post-resume snapshot. Fixing that
            # fully needs per-interaction snapshots (a real schema
            # change) rather than one row per session_id — left as a
            # known limitation given it requires bypassing the normal UI
            # flow to reach.
            answer_text = " ".join(
                t for t in (_render_prompt_spans(ui_request.get("prompt", [])) for _, _, ui_request in parsed) if t
            )

            # Wrapped in a savepoint: take_snapshot()/upsert_session_state
            # run after the ConversationTurn/UserInteraction rows are
            # already flushed, and the routers' SSE generators swallow any
            # exception here into an "error" event rather than letting it
            # propagate — which means get_db()'s outer commit would
            # otherwise happily persist an OPEN UserInteraction with no
            # AgentSessionState snapshot if upsert_session_state failed,
            # permanently breaking that interaction's resume. A failure
            # anywhere in this block must roll back all of it together.
            async with db.begin_nested():
                # ConversationTurn must be inserted (and flushed) before any
                # UserInteraction row that references it — user_interactions.
                # turn_id is a real FK, and SQLite/Postgres both enforce it
                # immediately, not deferred.
                db.add(ConversationTurn(
                    user_id=user_id, session_id=session_id, role="user",
                    content=user_turn_content, tool_calls=None,
                ))
                assistant_turn = ConversationTurn(
                    user_id=user_id, session_id=session_id, role="assistant",
                    content=answer_text, tool_calls=None,
                )
                assistant_turn.id = turn_id
                db.add(assistant_turn)
                await db.flush()

                # Any interaction from an EARLIER turn on this same session
                # is about to become unresumable — upsert_session_state
                # below keeps only one snapshot per session_id, so once it's
                # overwritten an older interrupt_id can never be found in
                # the loaded snapshot again. Expire them now so answering
                # one late fails cleanly (409) instead of surfacing a
                # confusing mid-resume error later. Interrupts Strands just
                # re-raised IN THIS SAME finalize call (this turn's own
                # still-open siblings, see the comment above) are excluded
                # — those aren't abandoned, they're mid-flight.
                await interactions_store.expire_stale_interactions_for_session(
                    db, user_id, session_id,
                    keep_interrupt_ids=[interrupt_id for interrupt_id, _, _ in parsed],
                )

                interaction_ids: List[str] = []
                for interrupt_id, tool_use_id, ui_request in parsed:
                    interaction = await interactions_store.get_or_create_interaction(
                        db, user_id, session_id, turn_id, interrupt_id, tool_use_id, ui_request,
                    )
                    interaction_ids.append(str(interaction.id))
                assistant_turn.tool_calls = [
                    {"type": "ui_request", "interaction_id": iid} for iid in interaction_ids
                ]

                snapshot = agent.take_snapshot(preset="session")
                await interactions_store.upsert_session_state(
                    db, user_id, session_id, snapshot.to_dict(), _installed_strands_version(),
                    awaiting_input=True,
                )

            logger.info(
                "StrandsOrchestrator: paused user=%s session=%s awaiting=%s",
                user_id, session_id_str, interaction_ids,
            )

            return {
                "answer": answer_text,
                "tools_used": tools_used,
                "sources": [],
                "session_id": session_id_str,
                "iterations": iterations,
                "turn_id": str(turn_id),
                "stop_reason": "interrupt",
                "awaiting": interaction_ids,
            }

        if result.stop_reason == "interrupt":
            # Every interrupt lacked a usable ui_request payload — genuinely
            # anomalous (request_user_input always sets one; this only fires
            # for some future interrupting tool that doesn't). Surface as an
            # error rather than claiming "interrupt" with nothing the client
            # can act on, or silently normalizing it away.
            logger.error(
                "StrandsOrchestrator: interrupt with no persistable ui_request for session=%s", session_id,
            )
            stop_reason = "error"
        else:
            stop_reason = _normalize_stop_reason(result.stop_reason)

        # result.message is precise for the common end_turn case, but for a
        # limit-triggered stop Strands sets it to agent.messages[-1] at the
        # moment the cap tripped (event_loop.py::_check_limits) — that can
        # be a user message or a dangling tool-use with no text. Fall back
        # to searching the full history so a degraded stop still surfaces
        # the last real assistant reply instead of an empty answer.
        answer = _extract_last_assistant_text([result.message]) or _extract_last_assistant_text(agent.messages)
        await self._persist_turns(
            db, user_id, session_id_str, user_turn_content, answer, assistant_turn_id=turn_id,
        )

        logger.info(
            "StrandsOrchestrator: completed user=%s tools=%s iterations=%d stop_reason=%s",
            user_id, tools_used, iterations, result.stop_reason,
        )

        return {
            "answer": answer,
            "tools_used": tools_used,
            "sources": [],   # Strands tools return results directly to the LLM; no separate source list
            "session_id": session_id_str,
            "iterations": iterations,
            "turn_id": str(turn_id),
            "stop_reason": stop_reason,
            "awaiting": [],
        }

    # ------------------------------------------------------------------
    # Agent construction
    # ------------------------------------------------------------------

    def _build_agent(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        user_tz: str,
        system_prompt: str,
        history: List[Dict[str, Any]],
        emit: Optional[StreamEmitter],
        session_id: uuid.UUID,
    ) -> Any:
        """Instantiate a Strands Agent for a single request.

        A new agent is created per request so there is no shared mutable
        state between concurrent queries.

        Uses SequentialToolExecutor: Strands runs multiple tool calls from one
        LLM turn concurrently by default, but every tool in make_agent_tools
        closes over this same AsyncSession, which is not safe for concurrent
        use from more than one task at a time (same reasoning as
        app/services/agent/knowledge/domain_agent.py's make_domain_agent).
        """
        from strands import Agent
        from strands.tools.executors import SequentialToolExecutor

        from app.services.agent.strands_model import build_openai_model
        from app.services.agent.strands_tools import make_agent_tools

        model = build_openai_model()

        tools = make_agent_tools(
            db=db,
            user_id=user_id,
            user_timezone=user_tz,
            embedder=self._embedder,
            session_id=session_id,
        )

        callback_handler = _StreamingCallbackHandler(emit)

        # Pre-load conversation history as Strands messages if available
        initial_messages = _history_to_strands_messages(history) if history else []

        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            callback_handler=callback_handler,
            messages=initial_messages,
            tool_executor=SequentialToolExecutor(),
        )

        return agent

    # ------------------------------------------------------------------
    # Session management (mirrored from MultiAgentOrchestrator)
    # ------------------------------------------------------------------

    async def _resolve_session(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: Optional[str],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Return (resolved_session_id, history_messages).

        Starts a new session if session_id is None, an invalid UUID, or
        the most recent turn exceeds SESSION_EXPIRY_HOURS.
        """
        if session_id is None:
            return str(uuid.uuid4()), []

        try:
            uuid.UUID(session_id)
        except ValueError:
            return str(uuid.uuid4()), []

        stmt = (
            select(ConversationTurn)
            .where(
                ConversationTurn.user_id == user_id,
                ConversationTurn.session_id == uuid.UUID(session_id),
            )
            .order_by(ConversationTurn.created_at.desc())
            .limit(CONVERSATION_WINDOW)
        )
        rows = (await db.execute(stmt)).scalars().all()

        if not rows:
            return session_id, []

        most_recent = rows[0]
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=SESSION_EXPIRY_HOURS)
        created = most_recent.created_at
        if created is not None:
            # Normalize to aware UTC for consistent comparison regardless of DB driver tz handling
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        if created is not None and created < cutoff:
            return str(uuid.uuid4()), []

        history = [
            {"role": turn.role, "content": turn.content}
            for turn in reversed(rows)
        ]
        return session_id, history

    async def _persist_turns(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        sid: str,
        question: str,
        answer: str,
        assistant_turn_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Write user + assistant ConversationTurn rows to the database.

        ``assistant_turn_id`` lets the caller pin the assistant row's id to
        the ``turn_id`` already announced in the SSE ``session`` event, so a
        client (and, from Fase 2 onward, a ``UserInteraction.turn_id`` FK)
        can correlate a stream to the row it produced without a second
        query. UUIDMixin defaults ``id`` to ``uuid.uuid4()`` either way, so
        omitting it (existing callers) is unaffected.
        """
        session_uuid = uuid.UUID(sid)

        db.add(ConversationTurn(
            user_id=user_id,
            session_id=session_uuid,
            role="user",
            content=question,
            tool_calls=None,
        ))

        assistant_turn = ConversationTurn(
            user_id=user_id,
            session_id=session_uuid,
            role="assistant",
            content=answer,
            tool_calls=None,  # Strands manages tool history internally
        )
        if assistant_turn_id is not None:
            assistant_turn.id = assistant_turn_id
        db.add(assistant_turn)

        await db.flush()

    # ------------------------------------------------------------------
    # User identity + style
    # ------------------------------------------------------------------

    async def _fetch_user_identity(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Tuple[Optional[str], Optional[str], str]:
        """Return (full_name, email, timezone) for user_id.

        Falls back to (None, None, "UTC") if the user record is not found.
        """
        from app.models.user import User

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            tz = user.timezone if user.timezone else "UTC"
            return user.full_name, user.email, tz
        return None, None, "UTC"

    async def _fetch_user_style(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Return the user's style/persona dict from StyleAnalyzerTool."""
        from app.services.agent.tools.style_analyzer import StyleAnalyzerTool

        return await StyleAnalyzerTool().get_style(db, user_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_system_prompt(
    today_str: str,
    user_name: Optional[str],
    user_email: Optional[str],
    user_timezone: str,
    style_text: str,
) -> str:
    """Compose the agent system prompt."""
    identity_line = (
        f"Usuario: {user_name} <{user_email}> | Timezone: {user_timezone}"
        if user_name
        else f"Timezone: {user_timezone}"
    )
    return f"""Sos un AI Chief of Staff personal.

Fecha de hoy: {today_str}
{identity_line}

Estilo de comunicación del usuario:
{style_text}

Workflow obligatorio:
1. get_calendar/get_emails consultan HOY por default si no les pasás nada — \
si la pregunta es sobre "mañana"/"ayer"/"hoy", pasales SIEMPRE ese día \
explícito como day= ("today"/"tomorrow"/"yesterday", en inglés o español, \
da igual) — nunca los llames sin day en esos casos. Es un parámetro simple, \
no hace falta calcular ninguna fecha. Para un día puntual que day= no cubre \
(una fecha del calendario, "el lunes que viene"), ahí sí llamá primero \
get_current_datetime y calculá vos el date="YYYY-MM-DD" real. La respuesta \
debe hablar siempre del día que realmente consultaste.
2. Si la pregunta es sobre una persona, proyecto o tema específico, probá primero \
query_knowledge — es la vista consolidada y con proveniencia que arman los agentes \
de dominio, y trae su propio nivel de confianza. Si no encontrás nada ahí, o \
necesitás más contexto crudo, usá search_memory y search_learnings. Si la pregunta \
pide lo más reciente/último/de esta semana sobre algo, llamá search_memory con \
sort="recent" — la similitud semántica sola no tiene noción de qué es reciente. \
Para preguntas acotadas a un día puntual (mails/eventos "de hoy", "de ayer"), usá \
get_emails/get_calendar en vez de search_memory — son filtros de fecha exactos, \
no similitud. Para "¿me mencionaron en Slack?" o similares, usá get_my_mentions \
— es un match exacto contra tu propia cuenta de Slack, no similitud semántica.
3. Al empezar la conversación (o cuando sea natural), llamá get_pending_questions — \
son dudas que los agentes de dominio no pudieron resolver solos y te piden que se \
las confirmes al humano. Si hay alguna relevante, planteala con naturalidad, no la \
fuerces en cada respuesta. Si el usuario confirma o corrige, llamá \
confirm_pending_answer para cerrar el loop — esa respuesta pasa a ser conocimiento \
de alta confianza.
4. Si el usuario te cuenta algo durable al pasar — una preferencia, una \
corrección, un hecho sobre una persona o proyecto que no estaba en tu \
contexto — llamá save_learning para que quede disponible en conversaciones \
futuras. No hace falta que te lo pidan explícitamente; distilar lo que vale \
la pena recordar es tu trabajo, no el del usuario.
5. Si el usuario te dice que un pendiente/compromiso está mal armado — es de \
otra persona, ya está resuelto, o tiene mal el texto — NUNCA respondas como si \
ya lo hubieras corregido: llamá propose_action con action_type="update_commitment" \
(describe_action_types te da el payload exacto) para que lo apruebe antes de \
aplicarse. Necesitás el commitment_id — si no lo tenés a mano, pedilo o buscalo \
con las tools de lectura primero.
6. get_calendar/get_emails/get_my_mentions devuelven lista vacía tanto si \
genuinamente no hay nada como si la sincronización de esa fuente está rota — \
la tool no puede distinguirlo. Antes de afirmar "no tenés reuniones/mails/etc." \
como una respuesta segura, llamá get_sync_status y fijate el campo "status" de \
la plataforma correspondiente (outlook/teams/slack): si dice "error", NO digas \
que no hay nada — contale al usuario que hay un problema de sincronización \
(podés citar el campo "error" si ayuda) en vez de una ausencia real de datos.
7. Llamá otras tools según lo requiera la pregunta
8. Sintetizá una respuesta clara y accionable

Respondé siempre en el idioma del usuario."""


def _format_style(style_info: Dict[str, Any]) -> str:
    """Convert StyleAnalyzerTool output to a compact string for the prompt."""
    parts: List[str] = []
    persona = style_info.get("persona_description", "")
    tone = style_info.get("tone_guidelines", "")
    if persona:
        parts.append(f"Persona: {persona}")
    if tone:
        parts.append(f"Tone: {tone}")
    return " | ".join(parts) if parts else "No style profile available."


def _history_to_strands_messages(
    history: List[Dict[str, Any]],
) -> "List[Message]":
    """Convert our DB history format to Strands message format.

    Strands messages are dicts with ``role`` and ``content`` where content
    is a list of content blocks: ``[{"text": "..."}]``.
    """
    messages: List[Dict[str, Any]] = []
    for turn in history:
        role = turn.get("role", "user")
        content_str = turn.get("content", "")
        messages.append({
            "role": role,
            "content": [{"text": content_str}],
        })
    return cast("List[Message]", messages)


def _render_prompt_spans(spans: List[Any]) -> str:
    """Flatten a UIRequest's rich-text prompt (List[TextSpan], as plain
    dicts here since it round-tripped through JSON) into plain text.

    Used as the interim assistant-turn content for a paused turn — until
    Fase 6's frontend renders the actual modal from the stored `spec`, this
    is what shows up in a plain conversation history view.
    """
    return "".join(s.get("text", "") for s in spans if isinstance(s, dict))


def _extract_last_assistant_text(messages: List[Any]) -> str:
    """Extract the last assistant message text from Strands agent messages list.

    Used after ``stream_async`` completes to retrieve the full answer since
    streaming does not return an ``AgentResult`` directly.
    """
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        text_parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        if text_parts:
            return " ".join(text_parts).strip()
    return ""
