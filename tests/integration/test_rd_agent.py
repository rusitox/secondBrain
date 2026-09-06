"""Tests for the Phase 6 I+D platform domain agent (MCP-backed).

Unlike test_domain_agent.py, this source has no documents table to seed —
its raw data comes from an MCP server, so MCPClient itself is mocked here
(never a real network call) alongside the Strands Agent/Swarm layer.
"""
import uuid
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
