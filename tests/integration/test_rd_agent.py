"""Tests for the Phase 6 I+D platform domain agent (MCP-backed).

Unlike test_domain_agent.py, this source has no documents table to seed —
its raw data comes from an MCP server, so MCPClient itself is mocked here
(never a real network call) alongside the Strands Agent/Swarm layer.
"""
import uuid
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import AgentConfig
from app.models.agent_run import AgentRun, RunStatus
from app.services import mcp_server_service
from app.services.agent.knowledge import rd_agent
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


def _fake_mcp_tool(name: str) -> Any:
    tool = MagicMock()
    tool.tool_name = name
    return tool


def _settings(mcp_url: str = "https://i-d-mcp.example.com/mcp", mcp_key: str = "test-token") -> MagicMock:
    settings = MagicMock()
    settings.id_brain_mcp_url = mcp_url
    settings.id_brain_mcp_api_key = mcp_key
    settings.llm_model = "openai/gpt-4o-mini"
    settings.llm_api_key = "sk-test"
    settings.openai_api_key = ""
    return settings


class TestRunRdDomainAgentSkipsWhenUnconfigured:
    async def test_no_mcp_url_returns_skipped_summary_without_touching_mcp(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="rd1@example.com")
        settings = _settings(mcp_url="")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient") as mock_mcp_client_cls:
            result = await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert result["source"] == "rd"
        assert "skipped" in result["summary"]
        mock_mcp_client_cls.assert_not_called()


class TestRunRdDomainAgentExcludesCreateTasks:
    async def test_create_tasks_excluded_from_agent_tools(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rd2@example.com")
        settings = _settings()

        mcp_tools = [_fake_mcp_tool("list_initiatives"), _fake_mcp_tool("list_tasks")]
        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = mcp_tools

        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance) as mock_mcp_client_cls, \
             patch("strands.Agent", return_value=mock_agent_instance) as mock_agent_cls:
            result = await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert result == {"source": "rd", "summary": "done"}

        # tool_filters passed to MCPClient rejects create_tasks at the transport layer.
        _, kwargs = mock_mcp_client_cls.call_args
        assert kwargs["tool_filters"] == {"rejected": ["create_tasks"]}

        # And the agent itself only ever sees the two MCP tools plus the
        # resolution-ladder tools — never a create_tasks tool object.
        _, agent_kwargs = mock_agent_cls.call_args
        tool_names = {getattr(t, "tool_name", getattr(t, "__name__", None)) for t in agent_kwargs["tools"]}
        assert "create_tasks" not in tool_names
        assert {"list_initiatives", "list_tasks"} <= tool_names
        assert {"find_or_create_entity", "add_claim", "consult_knowledge_base",
                "ask_peer_agents", "escalate_or_validate"} <= tool_names

        mock_client_instance.start.assert_called_once()
        mock_client_instance.stop.assert_called_once()


class TestRunRdDomainAgentRespectsConfig:
    async def test_disabled_via_config_skips_without_touching_mcp(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rd3@example.com")
        db_session.add(AgentConfig(user_id=user_id, agent_key="rd", enabled=False))
        await db_session.commit()
        settings = _settings()

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient") as mock_mcp_client_cls:
            result = await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert result == {"source": "rd", "summary": "skipped: disabled via agent config"}
        mock_mcp_client_cls.assert_not_called()

    async def test_model_and_prompt_override_reach_the_agent(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rd4@example.com")
        db_session.add(AgentConfig(
            user_id=user_id, agent_key="rd", model_id="openai/gpt-4o", system_prompt="custom rd prompt",
        ))
        await db_session.commit()
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = []
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance), \
             patch("strands.models.openai.OpenAIModel") as mock_model_cls, \
             patch("strands.Agent", return_value=mock_agent_instance) as mock_agent_cls:
            await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert mock_model_cls.call_args.kwargs["model_id"] == "gpt-4o"
        assert mock_agent_cls.call_args.kwargs["system_prompt"] == "custom rd prompt"

    async def test_enabled_tools_filters_resolution_ladder(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rd5@example.com")
        db_session.add(AgentConfig(user_id=user_id, agent_key="rd", enabled_tools=["add_claim"]))
        await db_session.commit()
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = [_fake_mcp_tool("list_initiatives")]
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance), \
             patch("strands.Agent", return_value=mock_agent_instance) as mock_agent_cls:
            await rd_agent.run_rd_domain_agent(db_session, user_id)

        tools_passed = mock_agent_cls.call_args.kwargs["tools"]
        tool_names = {getattr(t, "tool_name", None) for t in tools_passed}
        assert tool_names == {"list_initiatives", "add_claim"}

    async def test_leaked_create_tasks_raises_instead_of_silently_exposing_it(
        self, db_session: AsyncSession,
    ) -> None:
        """Defense in depth: even if tool_filters somehow failed server-side,
        a leaked create_tasks must blow up the run rather than reach the LLM."""
        user_id = await _make_persisted_user(db_session, email="rd3@example.com")
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = [_fake_mcp_tool("create_tasks")]

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance):
            with pytest.raises(RuntimeError, match="create_tasks"):
                await rd_agent.run_rd_domain_agent(db_session, user_id)

        # The client must still be stopped even though the run blew up.
        mock_client_instance.stop.assert_called_once()

    async def test_mcp_start_failure_still_stops_the_client(self, db_session: AsyncSession) -> None:
        """A dead/unreachable MCP server must not leak the client's resources —
        stop() must run even when start() itself is what fails."""
        user_id = await _make_persisted_user(db_session, email="rd5@example.com")
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.side_effect = ConnectionError("MCP server unreachable")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance):
            with pytest.raises(ConnectionError):
                await rd_agent.run_rd_domain_agent(db_session, user_id)

        mock_client_instance.stop.assert_called_once()
        mock_client_instance.list_tools_sync.assert_not_called()

    async def test_mcp_client_construction_failure_still_closes_out_the_run(
        self, db_session: AsyncSession,
    ) -> None:
        """MCPClient(...) itself can raise (e.g. a malformed url on a
        user-registered McpServer row) — this must still close the AgentRun
        as FAILED, not leave it orphaned at RUNNING forever, same as a
        failure inside .start()."""
        user_id = await _make_persisted_user(db_session, email="rd6@example.com")
        settings = _settings()

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", side_effect=ValueError("bad url")):
            with pytest.raises(ValueError):
                await rd_agent.run_rd_domain_agent(db_session, user_id)

        result = await db_session.execute(select(AgentRun).where(AgentRun.user_id == user_id))
        run = result.scalar_one()
        assert run.status == RunStatus.FAILED
        assert run.error == "bad url"


class TestRunRdDomainAgentUsesSharedResolutionLadder:
    async def test_resolution_ladder_tools_share_the_same_db_session(
        self, db_session: AsyncSession,
    ) -> None:
        """A quick smoke check that make_resolution_ladder_tools(source="rd", ...)
        is what's wired in — not a hand-rolled duplicate set of tools."""
        user_id = await _make_persisted_user(db_session, email="rd4@example.com")
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = []

        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        captured: List[Any] = []

        def _capture_agent(*args: Any, **kwargs: Any) -> Any:
            captured.extend(kwargs["tools"])
            return mock_agent_instance

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance), \
             patch("strands.Agent", side_effect=_capture_agent):
            await rd_agent.run_rd_domain_agent(db_session, user_id)

        add_claim_tool = next(t for t in captured if getattr(t, "tool_name", None) == "add_claim")
        result = await add_claim_tool.__wrapped__(entity_id=str(uuid.uuid4()), claim_text="x")
        # Not found (bogus entity_id) — proves this ran against the real
        # db_session via store.add_claim, not a stub.
        assert "error" in result


class TestRunRdDomainAgentUsesRegisteredMcpServer:
    """Phase 3 — AgentConfig.mcp_server_ids pointing at a real McpServer row
    takes over from the id_brain_mcp_url/id_brain_mcp_api_key env vars."""

    async def test_registered_server_url_and_key_reach_mcp_client(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rdmcp1@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="My I+D", url="https://user-registered.example.com/mcp",
            api_key="user-token",
        )
        db_session.add(AgentConfig(user_id=user_id, agent_key="rd", mcp_server_ids=[str(server.id)]))
        await db_session.commit()
        settings = _settings(mcp_url="")  # env unset — the registered server is the only source

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = []
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance) as mock_mcp_client_cls, \
             patch("strands.Agent", return_value=mock_agent_instance):
            result = await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert result == {"source": "rd", "summary": "done"}
        _, kwargs = mock_mcp_client_cls.call_args
        assert kwargs["url"] == "https://user-registered.example.com/mcp"
        assert kwargs["headers"] == {"Authorization": "Bearer user-token"}
        # create_tasks stays rejected even though it came from the DB row, not settings.
        assert "create_tasks" in kwargs["tool_filters"]["rejected"]

    async def test_disabled_registered_server_falls_back_to_env(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rdmcp2@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="Disabled", url="https://disabled.example.com/mcp", enabled=False,
        )
        db_session.add(AgentConfig(user_id=user_id, agent_key="rd", mcp_server_ids=[str(server.id)]))
        await db_session.commit()
        settings = _settings()  # env IS configured — should be the fallback

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = []
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance) as mock_mcp_client_cls, \
             patch("strands.Agent", return_value=mock_agent_instance):
            await rd_agent.run_rd_domain_agent(db_session, user_id)

        _, kwargs = mock_mcp_client_cls.call_args
        assert kwargs["url"] == settings.id_brain_mcp_url

    async def test_no_env_and_no_registered_server_skips(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="rdmcp3@example.com")
        settings = _settings(mcp_url="")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient") as mock_mcp_client_cls:
            result = await rd_agent.run_rd_domain_agent(db_session, user_id)

        assert result == {"source": "rd", "summary": "skipped: id_brain_mcp_url not configured"}
        mock_mcp_client_cls.assert_not_called()

    async def test_stale_mcp_server_id_falls_back_to_env(self, db_session: AsyncSession) -> None:
        """The referenced McpServer was deleted since — falls through to the
        env config exactly like an empty mcp_server_ids list."""
        user_id = await _make_persisted_user(db_session, email="rdmcp4@example.com")
        db_session.add(AgentConfig(
            user_id=user_id, agent_key="rd", mcp_server_ids=[str(uuid.uuid4())],
        ))
        await db_session.commit()
        settings = _settings()

        mock_client_instance = MagicMock()
        mock_client_instance.start.return_value = mock_client_instance
        mock_client_instance.list_tools_sync.return_value = []
        mock_agent_instance = MagicMock()
        mock_agent_instance.invoke_async = AsyncMock(return_value="done")

        with patch("app.services.agent.knowledge.rd_agent.get_settings", return_value=settings), \
             patch("strands.tools.mcp.MCPClient", return_value=mock_client_instance) as mock_mcp_client_cls, \
             patch("strands.Agent", return_value=mock_agent_instance):
            await rd_agent.run_rd_domain_agent(db_session, user_id)

        _, kwargs = mock_mcp_client_cls.call_args
        assert kwargs["url"] == settings.id_brain_mcp_url
