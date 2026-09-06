"""Unit tests for the knowledge agent scheduler (specs/plan-multi-agent-knowledge.md, Phase 8)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.knowledge.scheduler import KnowledgeAgentScheduler


def _settings(
    enable_knowledge_agents: bool = True,
    knowledge_agent_interval_minutes: int = 60,
    knowledge_agent_batch_size: int = 20,
    id_brain_mcp_url: str = "",
    openai_api_key: str = "",
) -> MagicMock:
    settings = MagicMock()
    settings.enable_knowledge_agents = enable_knowledge_agents
    settings.knowledge_agent_interval_minutes = knowledge_agent_interval_minutes
    settings.knowledge_agent_batch_size = knowledge_agent_batch_size
    settings.id_brain_mcp_url = id_brain_mcp_url
    settings.openai_api_key = openai_api_key
    return settings


class TestKnowledgeAgentSchedulerInit:
    def test_scheduler_creates_without_apscheduler(self) -> None:
        with patch("app.services.agent.knowledge.scheduler.HAS_APSCHEDULER", False):
            scheduler = KnowledgeAgentScheduler()
            assert not scheduler.is_available
            assert not scheduler.is_running

    def test_scheduler_creates_with_apscheduler(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        assert scheduler.is_available
        assert not scheduler.is_running


class TestKnowledgeAgentSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        with patch.object(scheduler, "_load_jobs", new_callable=AsyncMock):
            await scheduler.start()
            assert scheduler.is_running
            await scheduler.shutdown()
            assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_start_without_apscheduler(self) -> None:
        with patch("app.services.agent.knowledge.scheduler.HAS_APSCHEDULER", False):
            scheduler = KnowledgeAgentScheduler()
            await scheduler.start()
            assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        with patch.object(scheduler, "_load_jobs", new_callable=AsyncMock) as mock_load:
            await scheduler.start()
            await scheduler.start()
            mock_load.assert_called_once()
            await scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_without_start_is_noop(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        await scheduler.shutdown()
        assert not scheduler.is_running


class TestKnowledgeAgentSchedulerJobs:
    def test_get_job_info_empty(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        assert scheduler.get_job_info() == []

    def test_schedule_job_uses_configured_interval(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        user_id = uuid.uuid4()

        with patch("app.core.config.get_settings", return_value=_settings(knowledge_agent_interval_minutes=90)), \
             patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.add_job = MagicMock()
            scheduler._schedule_job(user_id)
            mock_sched.add_job.assert_called_once()
            call_kwargs = mock_sched.add_job.call_args
            trigger = call_kwargs.kwargs.get("trigger")
            assert trigger.interval.total_seconds() == 90 * 60
            assert call_kwargs.kwargs["id"] == f"knowledge_cycle_{user_id}"
            assert call_kwargs.kwargs["kwargs"] == {"user_id": str(user_id)}

    def test_minimum_interval_enforced(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        user_id = uuid.uuid4()

        with patch("app.core.config.get_settings", return_value=_settings(knowledge_agent_interval_minutes=1)), \
             patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.add_job = MagicMock()
            scheduler._schedule_job(user_id)
            trigger = mock_sched.add_job.call_args.kwargs["trigger"]
            assert trigger.interval.total_seconds() == 300  # clamped to 5 minutes


class TestLoadJobs:
    @pytest.mark.asyncio
    async def test_load_jobs_schedules_one_per_distinct_user(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = [(user_a,), (user_b,)]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            await scheduler._load_jobs()
            assert mock_schedule.call_count == 2

    @pytest.mark.asyncio
    async def test_load_jobs_empty(self) -> None:
        scheduler = KnowledgeAgentScheduler()

        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            await scheduler._load_jobs()
            mock_schedule.assert_not_called()


def _make_fresh_session_factory():
    """Returns (factory, sessions) — factory mints a brand-new AsyncMock session on
    every call (like a real async_sessionmaker), instead of handing back one shared
    mock, so tests can actually verify each step got its own fresh session."""
    sessions: list = []

    def _new_session() -> AsyncMock:
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sessions.append(session)
        return session

    factory = MagicMock(side_effect=_new_session)
    return factory, sessions


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_runs_every_document_backed_source_plus_reconciliation_when_rd_unconfigured(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        user_id = str(uuid.uuid4())

        mock_factory, sessions = _make_fresh_session_factory()

        mock_run_domain_agent = AsyncMock(return_value={"source": "x", "summary": "ok"})
        mock_run_rd_agent = AsyncMock()
        mock_run_reconciliation = AsyncMock(return_value={"merged": 0})

        with patch("app.core.config.get_settings", return_value=_settings(id_brain_mcp_url="")), \
             patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.services.agent.knowledge.domain_agent.run_domain_agent", mock_run_domain_agent), \
             patch("app.services.agent.knowledge.rd_agent.run_rd_domain_agent", mock_run_rd_agent), \
             patch("app.services.agent.knowledge.reconciliation.run_reconciliation", mock_run_reconciliation):
            await scheduler._run_cycle(user_id)

        # 5 document-backed sources (Platform enum), never "rd" since it's unconfigured.
        assert mock_run_domain_agent.call_count == 5
        called_sources = {call.args[0] for call in mock_run_domain_agent.call_args_list}
        assert "rd" not in called_sources
        mock_run_rd_agent.assert_not_called()
        mock_run_reconciliation.assert_called_once()
        # 5 sources + reconciliation — each got its OWN fresh session (not one shared mock).
        assert mock_factory.call_count == 6
        assert len(sessions) == 6
        assert all(s.commit.await_count == 1 for s in sessions)
        assert all(s.rollback.await_count == 0 for s in sessions)

    @pytest.mark.asyncio
    async def test_runs_rd_agent_when_configured(self) -> None:
        scheduler = KnowledgeAgentScheduler()
        user_id = str(uuid.uuid4())

        mock_factory, sessions = _make_fresh_session_factory()

        mock_run_domain_agent = AsyncMock(return_value={})
        mock_run_rd_agent = AsyncMock(return_value={"source": "rd", "summary": "ok"})
        mock_run_reconciliation = AsyncMock(return_value={})

        with patch("app.core.config.get_settings", return_value=_settings(id_brain_mcp_url="https://mcp.example.com")), \
             patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.services.agent.knowledge.domain_agent.run_domain_agent", mock_run_domain_agent), \
             patch("app.services.agent.knowledge.rd_agent.run_rd_domain_agent", mock_run_rd_agent), \
             patch("app.services.agent.knowledge.reconciliation.run_reconciliation", mock_run_reconciliation):
            await scheduler._run_cycle(user_id)

        mock_run_rd_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_source_failing_does_not_block_the_others(self) -> None:
        """A domain agent raising must not stop the rest of the cycle — each
        step gets its own session and its own isolated failure."""
        scheduler = KnowledgeAgentScheduler()
        user_id = str(uuid.uuid4())

        mock_factory, sessions = _make_fresh_session_factory()

        mock_run_domain_agent = AsyncMock(side_effect=[RuntimeError("boom"), {}, {}, {}, {}])
        mock_run_reconciliation = AsyncMock(return_value={})

        with patch("app.core.config.get_settings", return_value=_settings(id_brain_mcp_url="")), \
             patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.services.agent.knowledge.domain_agent.run_domain_agent", mock_run_domain_agent), \
             patch("app.services.agent.knowledge.reconciliation.run_reconciliation", mock_run_reconciliation):
            await scheduler._run_cycle(user_id)  # must not raise

        assert mock_run_domain_agent.call_count == 5
        mock_run_reconciliation.assert_called_once()
        # 5 sources + reconciliation, each on its own fresh session.
        assert mock_factory.call_count == 6
        # Only the first session (the one whose call raised) rolls back; the
        # other 5 — including reconciliation's — commit normally.
        assert sessions[0].rollback.await_count == 1
        assert sessions[0].commit.await_count == 0
        assert all(s.commit.await_count == 1 for s in sessions[1:])
        assert all(s.rollback.await_count == 0 for s in sessions[1:])

    @pytest.mark.asyncio
    async def test_rollback_failure_does_not_abort_the_rest_of_the_cycle(self) -> None:
        """The Warning fix: if db.rollback() itself raises (e.g. a broken
        connection), that must be swallowed too — it must never escape and
        abort the remaining steps in the cycle."""
        scheduler = KnowledgeAgentScheduler()
        user_id = str(uuid.uuid4())

        first_call = {"seen": False}

        def _new_session_first_rollback_broken() -> AsyncMock:
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
            if not first_call["seen"]:
                first_call["seen"] = True
                session.rollback = AsyncMock(side_effect=RuntimeError("connection already closed"))
            return session

        mock_factory = MagicMock(side_effect=_new_session_first_rollback_broken)

        mock_run_domain_agent = AsyncMock(side_effect=[RuntimeError("boom"), {}, {}, {}, {}])
        mock_run_reconciliation = AsyncMock(return_value={})

        with patch("app.core.config.get_settings", return_value=_settings(id_brain_mcp_url="")), \
             patch("app.services.agent.knowledge.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.services.agent.knowledge.domain_agent.run_domain_agent", mock_run_domain_agent), \
             patch("app.services.agent.knowledge.reconciliation.run_reconciliation", mock_run_reconciliation):
            await scheduler._run_cycle(user_id)  # must not raise even though rollback() itself raised

        assert mock_run_domain_agent.call_count == 5
        mock_run_reconciliation.assert_called_once()
