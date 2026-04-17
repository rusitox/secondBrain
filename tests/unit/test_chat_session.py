"""Unit tests for CLI chat session."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cli.api_client import APIClient, APIError
from cli.chat import ChatSession
from cli.config import CLIConfig


def _make_config(**overrides) -> CLIConfig:
    defaults = dict(
        server_url="http://test:8000",
        user_id="user-123",
        user_name="Test User",
        user_email="test@test.com",
        onboarding_completed=True,
        onboarding_step=5,
        platforms_connected=["slack"],
        identity_configured=True,
        initial_import_done=True,
        preferences={"briefing_hour": 7, "briefing_minute": 0},
    )
    defaults.update(overrides)
    config = CLIConfig(**defaults)
    config.save = MagicMock()
    return config


def _make_api() -> APIClient:
    api = MagicMock(spec=APIClient)
    api.agent_query = AsyncMock(return_value={
        "answer": "You have 2 pending tasks.",
        "tools_used": ["memory", "tasks"],
        "sources": [{"id": "1"}, {"id": "2"}],
    })
    api.get_user_stats = AsyncMock(return_value={
        "documents_total": 50, "commitments_pending": 3,
        "commitments_overdue": 0, "integrations_active": 1,
        "integrations_total": 1, "last_sync": None,
    })
    api.close = AsyncMock()
    return api


class TestChatSessionQuery:
    @pytest.mark.asyncio
    async def test_query_calls_agent(self) -> None:
        api = _make_api()
        config = _make_config()
        session = ChatSession(api=api, config=config)
        session._prompt_session = None  # Force fallback input

        await session._handle_query("What's pending?")
        api.agent_query.assert_awaited_once_with("What's pending?")

    @pytest.mark.asyncio
    async def test_query_api_error_handled(self) -> None:
        api = _make_api()
        api.agent_query = AsyncMock(side_effect=APIError(500, "Internal error"))
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise
        await session._handle_query("test question")

    @pytest.mark.asyncio
    async def test_query_503_shows_warning(self) -> None:
        api = _make_api()
        api.agent_query = AsyncMock(side_effect=APIError(503, "Unavailable"))
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise, shows warning
        await session._handle_query("test question")

    @pytest.mark.asyncio
    async def test_query_empty_answer(self) -> None:
        api = _make_api()
        api.agent_query = AsyncMock(return_value={"answer": "", "tools_used": [], "sources": []})
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise
        await session._handle_query("test")


class TestChatSessionLoop:
    @pytest.mark.asyncio
    async def test_quit_command_exits(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Simulate: user types /quit
        with patch.object(session, "_get_input", AsyncMock(side_effect=["/quit"])):
            with patch.object(session, "_show_welcome", AsyncMock()):
                await session.run()

        api.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_eof_exits(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Simulate: EOF
        with patch.object(session, "_get_input", AsyncMock(return_value=None)):
            with patch.object(session, "_show_welcome", AsyncMock()):
                await session.run()

        api.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_input_continues(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Empty input, then quit
        with patch.object(session, "_get_input", AsyncMock(side_effect=["", "  ", "/quit"])):
            with patch.object(session, "_show_welcome", AsyncMock()):
                await session.run()

        api.agent_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_then_quit(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        with patch.object(session, "_get_input", AsyncMock(side_effect=["What's up?", "/quit"])):
            with patch.object(session, "_show_welcome", AsyncMock()):
                await session.run()

        api.agent_query.assert_awaited_once_with("What's up?")


class TestChatSessionWelcome:
    @pytest.mark.asyncio
    async def test_welcome_fetches_stats(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        await session._show_welcome()
        api.get_user_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_welcome_handles_stats_error(self) -> None:
        api = _make_api()
        api.get_user_stats = AsyncMock(side_effect=APIError(500, "Error"))
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise
        await session._show_welcome()

    @pytest.mark.asyncio
    async def test_welcome_no_user(self) -> None:
        api = _make_api()
        session = ChatSession(api=api, config=_make_config(user_id=None))
        session._prompt_session = None

        # Should not raise, just skip stats
        await session._show_welcome()
        api.get_user_stats.assert_not_awaited()
