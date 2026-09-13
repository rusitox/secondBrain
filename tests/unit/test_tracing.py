"""Tests for app.services.agent.tracing — the knowledge-backoffice run/event
recorder (specs/plan-knowledge-backoffice.md, Phase 1).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from typing import List

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, RunStatus, RunTrigger, RunType
from app.models.agent_run_event import AgentRunEvent, RunEventType
from app.services.agent import tracing
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


async def _events_for(db: AsyncSession, run_id: uuid.UUID) -> List[AgentRunEvent]:
    result = await db.execute(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.seq)
    )
    return list(result.scalars().all())


class _FakeAgent:
    """Duck-types the parts of a Strands Agent that tracing reads."""

    def __init__(self, messages, accumulated_usage=None) -> None:
        self.messages = messages
        if accumulated_usage is not None:
            self.event_loop_metrics = MagicMock(accumulated_usage=accumulated_usage)


class _FakeSwarmNode:
    def __init__(self, node_id: str, executor) -> None:
        self.node_id = node_id
        self.executor = executor


class _FakeSwarmResult:
    def __init__(self, node_history) -> None:
        self.node_history = node_history
        self.accumulated_usage = {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}


class TestStartAndFinishRun:
    async def test_start_run_persists_row_and_returns_id(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace1@example.com")

        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            model_id="gpt-4o",
        )

        assert run_id is not None
        run = await db_session.get(AgentRun, run_id)
        assert run is not None
        assert run.agent_key == "slack"
        assert run.run_type == RunType.DOMAIN_AGENT
        assert run.trigger == RunTrigger.MANUAL
        assert run.status == RunStatus.RUNNING
        assert run.model_id == "gpt-4o"
        assert run.finished_at is None

    async def test_finish_run_sets_status_timing_and_tokens(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace2@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )

        await tracing.finish_run(
            run_id, RunStatus.COMPLETED, summary="done",
            stats={"documents": 3},
            usage_source={"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
        )

        run = await db_session.get(AgentRun, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.summary == "done"
        assert run.stats == {"documents": 3}
        assert run.input_tokens == 100
        assert run.output_tokens == 50
        assert run.total_tokens == 150
        assert run.finished_at is not None
        assert run.duration_ms is not None

    async def test_finish_run_with_none_run_id_is_a_no_op(self) -> None:
        await tracing.finish_run(None, RunStatus.COMPLETED, summary="ignored")

    async def test_finish_run_ignores_non_mapping_usage(self, db_session: AsyncSession) -> None:
        """A mocked Agent's event_loop_metrics.accumulated_usage is a MagicMock,
        not a dict — must not crash finish_run or block the status update."""
        user_id = await _make_persisted_user(db_session, email="trace3@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )

        await tracing.finish_run(run_id, RunStatus.COMPLETED, usage_source=MagicMock())

        run = await db_session.get(AgentRun, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.input_tokens is None

    async def test_finish_run_extracts_usage_from_agent_shaped_source(
        self, db_session: AsyncSession,
    ) -> None:
        """usage_source=agent (event_loop_metrics.accumulated_usage) — the
        run_domain_agent/run_rd_domain_agent/StrandsOrchestrator.query shape."""
        user_id = await _make_persisted_user(db_session, email="trace3b@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        agent = _FakeAgent(messages=[], accumulated_usage={"inputTokens": 7, "outputTokens": 3, "totalTokens": 10})

        await tracing.finish_run(run_id, RunStatus.COMPLETED, usage_source=agent)

        run = await db_session.get(AgentRun, run_id)
        assert run.total_tokens == 10

    async def test_finish_run_extracts_usage_from_swarm_result_shaped_source(
        self, db_session: AsyncSession,
    ) -> None:
        """usage_source=swarm_result (.accumulated_usage directly, no
        event_loop_metrics indirection) — the negotiation-run shape."""
        user_id = await _make_persisted_user(db_session, email="trace3c@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION, trigger=RunTrigger.MANUAL,
        )
        swarm_result = _FakeSwarmResult([])

        await tracing.finish_run(run_id, RunStatus.COMPLETED, usage_source=swarm_result)

        run = await db_session.get(AgentRun, run_id)
        assert run.total_tokens == 15  # set by _FakeSwarmResult

    async def test_finish_run_usage_extraction_never_raises(self, db_session: AsyncSession) -> None:
        """A usage_source whose attribute access itself raises (not just
        AttributeError) must not prevent the status update from committing —
        this is the exact gap Warning 1 flagged: getattr's default only
        catches AttributeError, so extraction must run inside finish_run's
        own try/except, not be computed by the caller beforehand."""
        class _Explodes:
            @property
            def event_loop_metrics(self):
                raise TypeError("boom")

        user_id = await _make_persisted_user(db_session, email="trace3d@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )

        await tracing.finish_run(run_id, RunStatus.COMPLETED, summary="ok", usage_source=_Explodes())

        run = await db_session.get(AgentRun, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.summary == "ok"
        assert run.input_tokens is None

    async def test_start_run_survives_db_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _broken_factory():
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(tracing, "get_session_factory", _broken_factory)
        run_id = await tracing.start_run(
            uuid.uuid4(), agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        assert run_id is None


class TestRecordAgentEvents:
    async def test_serializes_text_tool_call_and_tool_result(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace4@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        agent = _FakeAgent(messages=[
            {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "t1", "name": "find_or_create_entity", "input": {"name": "X"}}},
            ]},
            {"role": "user", "content": [
                {"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"text": "ok"}]}},
            ]},
            {"role": "assistant", "content": [{"text": "Listo."}]},
        ])

        await tracing.record_agent_events(run_id, agent, actor="slack_domain_agent")

        events = await _events_for(db_session, run_id)
        assert [e.event_type for e in events] == [
            RunEventType.TOOL_CALL, RunEventType.TOOL_RESULT, RunEventType.ASSISTANT_TEXT,
        ]
        assert events[0].tool_name == "find_or_create_entity"
        assert events[0].payload["input"] == {"name": "X"}
        assert events[1].payload["status"] == "success"
        assert events[2].payload["text"] == "Listo."
        assert all(e.actor == "slack_domain_agent" for e in events)
        assert [e.seq for e in events] == [0, 1, 2]

    async def test_skips_plain_user_text_blocks(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace5@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        agent = _FakeAgent(messages=[{"role": "user", "content": [{"text": "the task prompt"}]}])

        await tracing.record_agent_events(run_id, agent, actor="x")

        assert await _events_for(db_session, run_id) == []

    async def test_non_list_messages_is_a_no_op(self, db_session: AsyncSession) -> None:
        """A MagicMock Agent's .messages attribute is itself a MagicMock, not a
        list — must not raise (this is what mocked-Agent tests hit)."""
        user_id = await _make_persisted_user(db_session, email="trace6@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )

        await tracing.record_agent_events(run_id, MagicMock(), actor="x")

        assert await _events_for(db_session, run_id) == []

    async def test_second_call_continues_seq(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace7@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        first = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": "one"}]}])
        second = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": "two"}]}])

        await tracing.record_agent_events(run_id, first, actor="a")
        await tracing.record_agent_events(run_id, second, actor="b")

        events = await _events_for(db_session, run_id)
        assert [e.seq for e in events] == [0, 1]
        assert [e.actor for e in events] == ["a", "b"]

    async def test_large_payload_is_truncated(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace8@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )
        huge_text = "x" * (tracing.TRACE_MAX_PAYLOAD_CHARS * 2)
        agent = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": huge_text}]}])

        await tracing.record_agent_events(run_id, agent, actor="x")

        events = await _events_for(db_session, run_id)
        assert events[0].payload["truncated"] is True
        assert len(events[0].payload["preview"]) <= tracing.TRACE_MAX_PAYLOAD_CHARS


class TestRecordSwarmNegotiation:
    async def test_records_handoffs_and_each_node_conversation(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace9@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION, trigger=RunTrigger.MANUAL,
        )
        agent_a = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": "a says hi"}]}])
        agent_b = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": "b agrees"}]}])
        swarm_result = _FakeSwarmResult([
            _FakeSwarmNode("slack_negotiator", agent_a),
            _FakeSwarmNode("outlook_negotiator", agent_b),
        ])

        await tracing.record_swarm_negotiation(run_id, swarm_result)

        events = await _events_for(db_session, run_id)
        assert [e.event_type for e in events] == [
            RunEventType.HANDOFF, RunEventType.ASSISTANT_TEXT, RunEventType.ASSISTANT_TEXT,
        ]
        assert events[0].actor == "slack_negotiator"
        assert events[0].payload["to"] == "outlook_negotiator"

    async def test_single_node_history_has_no_handoff(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace10@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION, trigger=RunTrigger.MANUAL,
        )
        agent_a = _FakeAgent(messages=[{"role": "assistant", "content": [{"text": "solo"}]}])
        swarm_result = _FakeSwarmResult([_FakeSwarmNode("slack_negotiator", agent_a)])

        await tracing.record_swarm_negotiation(run_id, swarm_result)

        events = await _events_for(db_session, run_id)
        assert [e.event_type for e in events] == [RunEventType.ASSISTANT_TEXT]

    async def test_mocked_swarm_result_is_a_no_op(self, db_session: AsyncSession) -> None:
        """strands.multiagent.Swarm mocked wholesale in a caller's test (as
        every existing domain_agent/reconciliation test does) yields a
        MagicMock() return value whose .node_history is itself a MagicMock,
        not a list — must not raise."""
        user_id = await _make_persisted_user(db_session, email="trace11@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION, trigger=RunTrigger.MANUAL,
        )

        await tracing.record_swarm_negotiation(run_id, MagicMock())
        await tracing.record_swarm_negotiation(run_id, None)

        assert await _events_for(db_session, run_id) == []


class TestVerdictAndErrorEvents:
    async def test_record_verdict_event(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace12@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION, trigger=RunTrigger.MANUAL,
        )

        await tracing.record_verdict_event(run_id, actor="ask_peer_agents", payload={"resolved": True})

        events = await _events_for(db_session, run_id)
        assert len(events) == 1
        assert events[0].event_type == RunEventType.VERDICT
        assert events[0].payload == {"resolved": True}

    async def test_record_error_event(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="trace13@example.com")
        run_id = await tracing.start_run(
            user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
        )

        await tracing.record_error_event(run_id, actor="slack_domain_agent", error="boom")

        events = await _events_for(db_session, run_id)
        assert events[0].event_type == RunEventType.ERROR
        assert events[0].payload == {"error": "boom"}


class TestSharedTestConnectionCaveat:
    """Documents a real limitation of this test suite, not a production behavior.

    tests/conftest.py's in-memory SQLite engine uses StaticPool (SQLAlchemy's
    default for `sqlite+aiosqlite://` memory URLs — confirmed by inspecting
    test_engine.pool) — every AsyncSession in the whole suite, including the ones
    tracing opens for itself, shares one physical connection. In production
    (Postgres, a real pool) tracing's session and a caller's session get distinct
    connections, so a trace survives the caller's rollback and vice versa — see
    tracing.py's module docstring. In *this* SQLite setup, since it's the same
    connection, tracing's `await db.commit()` commits whatever the caller's
    session had pending too, and a caller's later `rollback()` can't undo a
    tracing write that already landed.

    These tests exist to (a) confirm tracing still successfully writes rows
    even while a caller's session has an open, uncommitted transaction — the
    thing Phase 1 actually needs to work — and (b) pin down the shared-commit
    side effect explicitly, so it reads as "known, tested caveat" instead of
    silently surprising whoever next touches conftest.py's engine setup.
    """

    async def test_tracing_writes_succeed_with_an_open_caller_transaction(
        self, setup_test_db: None,
    ) -> None:
        from tests.conftest import test_session_factory

        async with test_session_factory() as caller_db:
            user = make_user(email="caveat1@example.com")
            caller_db.add(user)
            await caller_db.flush()  # caller's transaction is open, not committed
            user_id = user.id

            run_id = await tracing.start_run(
                user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            )
            assert run_id is not None
            await caller_db.commit()

        async with test_session_factory() as check:
            assert await check.get(AgentRun, run_id) is not None

    async def test_caveat_callers_rollback_does_not_undo_a_tracing_write(
        self, setup_test_db: None,
    ) -> None:
        """Not a desired property — the opposite of the production isolation
        guarantee — recorded so a future conftest.py change that happens to
        fix it doesn't need this test rewritten as a failure first."""
        from tests.conftest import test_session_factory

        async with test_session_factory() as caller_db:
            user = make_user(email="caveat2@example.com")
            caller_db.add(user)
            await caller_db.flush()
            user_id = user.id

            run_id = await tracing.start_run(
                user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            )
            await caller_db.rollback()

        async with test_session_factory() as check:
            # Same shared connection => tracing's commit landed the caller's
            # pending insert too, so the "rolled back" user still exists.
            assert await check.get(AgentRun, run_id) is not None


class TestPruneTraces:
    async def test_deletes_runs_older_than_retention_and_cascades_events(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="prune1@example.com")
        old_run = AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            started_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
        recent_run = AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            started_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        db_session.add_all([old_run, recent_run])
        await db_session.flush()
        db_session.add(AgentRunEvent(
            run_id=old_run.id, seq=0, event_type=RunEventType.ASSISTANT_TEXT, payload={"text": "old"},
        ))
        await db_session.commit()
        old_run_id, recent_run_id = old_run.id, recent_run.id

        deleted = await tracing.prune_traces(db_session, user_id, retention_days=30)
        await db_session.commit()

        assert deleted == 1
        assert await db_session.get(AgentRun, old_run_id) is None
        assert await db_session.get(AgentRun, recent_run_id) is not None
        assert await _events_for(db_session, old_run_id) == []

    async def test_scoped_by_user(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="prune2a@example.com")
        user_b = await _make_persisted_user(db_session, email="prune2b@example.com")
        old_run_a = AgentRun(
            user_id=user_a, agent_key="slack", run_type=RunType.DOMAIN_AGENT, trigger=RunTrigger.MANUAL,
            started_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
        db_session.add(old_run_a)
        await db_session.commit()

        deleted = await tracing.prune_traces(db_session, user_b, retention_days=30)
        await db_session.commit()

        assert deleted == 0
        assert await db_session.get(AgentRun, old_run_a.id) is not None

    async def test_failure_returns_zero_without_raising(self, db_session: AsyncSession) -> None:
        broken_session = MagicMock()
        broken_session.execute = AsyncMock(side_effect=RuntimeError("boom"))
        deleted = await tracing.prune_traces(broken_session, uuid.uuid4(), retention_days=30)
        assert deleted == 0
