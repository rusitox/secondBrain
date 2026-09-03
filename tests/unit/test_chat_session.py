"""Unit tests for CLI chat session."""
import pytest
import httpx
from typing import Any, AsyncGenerator, List, Optional, Tuple
from unittest.mock import ANY, AsyncMock, MagicMock, patch, call

from cli.api_client import APIClient, APIError, _AGENT_TIMEOUT, _DEFAULT_TIMEOUT
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


def _make_stream_generator(
    answer: str = "You have 2 pending tasks.",
    tools: Optional[List[str]] = None,
) -> Any:
    """Return an async-generator function that yields token + done events."""
    _tools = tools or []

    async def _stream(
        question: str, session_id: Optional[str] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        yield "token", {"text": answer}
        yield "done", {"session_id": "test-session", "iterations": 1, "tools_used": _tools}

    return _stream


def _make_api() -> APIClient:
    api = MagicMock(spec=APIClient)
    api.agent_query = AsyncMock(return_value={
        "answer": "You have 2 pending tasks.",
        "tools_used": ["memory", "tasks"],
        "sources": [{"id": "1"}, {"id": "2"}],
    })
    # Default streaming path used by _handle_query
    api.agent_query_stream = _make_stream_generator()
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

        calls: List[Tuple[str, Any]] = []

        async def _tracked(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            calls.append((question, session_id))
            yield "done", {"session_id": "sid", "iterations": 1, "tools_used": []}

        api.agent_query_stream = _tracked

        await session._handle_query("What's pending?")
        assert len(calls) == 1
        assert calls[0][0] == "What's pending?"

    @pytest.mark.asyncio
    async def test_query_api_error_handled(self) -> None:
        api = _make_api()

        async def _error_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            raise APIError(500, "Internal error")
            yield  # make it a generator

        api.agent_query_stream = _error_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise
        await session._handle_query("test question")

    @pytest.mark.asyncio
    async def test_query_503_shows_warning(self) -> None:
        api = _make_api()

        async def _error_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            raise APIError(503, "Unavailable")
            yield  # make it a generator

        api.agent_query_stream = _error_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise, shows warning
        await session._handle_query("test question")

    @pytest.mark.asyncio
    async def test_query_empty_answer(self) -> None:
        api = _make_api()

        async def _empty_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            yield "done", {"session_id": "sid", "iterations": 1, "tools_used": []}

        api.agent_query_stream = _empty_stream
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
        calls: List[Tuple[str, Any]] = []

        async def _tracked(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            calls.append((question, session_id))
            yield "done", {"session_id": "sid", "iterations": 1, "tools_used": []}

        api.agent_query_stream = _tracked
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        with patch.object(session, "_get_input", AsyncMock(side_effect=["What's up?", "/quit"])):
            with patch.object(session, "_show_welcome", AsyncMock()):
                await session.run()

        assert len(calls) == 1
        assert calls[0][0] == "What's up?"


class TestChatSessionWelcome:
    @pytest.mark.asyncio
    async def test_welcome_calls_agent_query(self) -> None:
        """Welcome should call agent_query with the welcome prompt."""
        api = _make_api()
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        await session._show_welcome()
        api.agent_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_welcome_agent_error_falls_back_to_static(self) -> None:
        """If agent_query fails, fallback to static stats panel (no crash)."""
        api = _make_api()
        api.agent_query = AsyncMock(side_effect=APIError(500, "Error"))
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Should not raise; fallback calls get_user_stats
        await session._show_welcome()
        api.get_user_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_welcome_agent_timeout_falls_back_to_static(self) -> None:
        """If agent_query times out, fallback to static stats panel."""
        api = _make_api()
        api.agent_query = AsyncMock(
            side_effect=httpx.ReadTimeout("timeout", request=None)
        )
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        await session._show_welcome()
        api.get_user_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_welcome_no_user_skips_agent(self) -> None:
        """Without user_id, skip agent call and show static fallback."""
        api = _make_api()
        session = ChatSession(api=api, config=_make_config(user_id=None))
        session._prompt_session = None

        await session._show_welcome()
        api.agent_query.assert_not_awaited()


# ---------------------------------------------------------------------------
# Helpers shared by timeout tests
# ---------------------------------------------------------------------------

def _make_real_api_client() -> APIClient:
    """Return a real APIClient instance (not a MagicMock) for low-level tests."""
    return APIClient(server_url="http://test:8000", user_id="user-123")


def _stub_http_response(status: int = 200, body: dict = None) -> MagicMock:
    """Return a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body or {"answer": "ok", "tools_used": [], "sources": []}
    return resp


# ---------------------------------------------------------------------------
# TestAgentQueryTimeout — agent_query() must use _AGENT_TIMEOUT (120 s)
# ---------------------------------------------------------------------------

class TestAgentQueryTimeout:
    @pytest.mark.asyncio
    async def test_agent_query_uses_agent_timeout_not_default(self) -> None:
        """agent_query() must pass _AGENT_TIMEOUT (120 s) to client.request(), not 30 s."""
        api = _make_real_api_client()
        mock_request = AsyncMock(return_value=_stub_http_response())

        with patch.object(api, "_get_client") as mock_get_client:
            mock_http_client = MagicMock()
            mock_http_client.request = mock_request
            mock_get_client.return_value = mock_http_client

            await api.agent_query("What's on my plate today?")

        # The timeout kwarg forwarded to client.request() must equal _AGENT_TIMEOUT
        _, kwargs = mock_request.call_args
        assert kwargs["timeout"] is _AGENT_TIMEOUT, (
            "agent_query() must forward _AGENT_TIMEOUT to client.request()"
        )

    @pytest.mark.asyncio
    async def test_agent_query_timeout_is_not_default_timeout(self) -> None:
        """Verify _AGENT_TIMEOUT and _DEFAULT_TIMEOUT are distinct objects with different values."""
        assert _AGENT_TIMEOUT is not _DEFAULT_TIMEOUT
        # Agent timeout read — 120 s; default read — 30 s
        assert _AGENT_TIMEOUT.read == 120.0
        assert _DEFAULT_TIMEOUT.read == 30.0


# ---------------------------------------------------------------------------
# TestRequestTimeout — _request() forwards timeout to client.request()
# ---------------------------------------------------------------------------

class TestRequestTimeout:
    @pytest.mark.asyncio
    async def test_request_forwards_custom_timeout_to_http_client(self) -> None:
        """_request() must pass the caller-supplied timeout directly to client.request()."""
        api = _make_real_api_client()
        custom_timeout = httpx.Timeout(60.0, connect=5.0)
        mock_request = AsyncMock(return_value=_stub_http_response())

        with patch.object(api, "_get_client") as mock_get_client:
            mock_http_client = MagicMock()
            mock_http_client.request = mock_request
            mock_get_client.return_value = mock_http_client

            await api._request("GET", "/test", timeout=custom_timeout)

        _, kwargs = mock_request.call_args
        assert kwargs["timeout"] is custom_timeout

    @pytest.mark.asyncio
    async def test_request_uses_default_timeout_when_none_given(self) -> None:
        """_request() must fall back to _DEFAULT_TIMEOUT when no timeout is supplied."""
        api = _make_real_api_client()
        mock_request = AsyncMock(return_value=_stub_http_response())

        with patch.object(api, "_get_client") as mock_get_client:
            mock_http_client = MagicMock()
            mock_http_client.request = mock_request
            mock_get_client.return_value = mock_http_client

            await api._request("GET", "/test")

        _, kwargs = mock_request.call_args
        assert kwargs["timeout"] is _DEFAULT_TIMEOUT

    @pytest.mark.asyncio
    async def test_request_timeout_is_not_swallowed(self) -> None:
        """A timeout raised by httpx must propagate out of _request() unchanged."""
        api = _make_real_api_client()

        with patch.object(api, "_get_client") as mock_get_client:
            mock_http_client = MagicMock()
            mock_http_client.request = AsyncMock(
                side_effect=httpx.ReadTimeout("timed out", request=None)
            )
            mock_get_client.return_value = mock_http_client

            with pytest.raises(httpx.ReadTimeout):
                await api._request("GET", "/test")


# ---------------------------------------------------------------------------
# TestHandleQueryTimeout — _handle_query() catches TimeoutException gracefully
# ---------------------------------------------------------------------------

class TestHandleQueryTimeout:
    @pytest.mark.asyncio
    async def test_handle_query_read_timeout_shows_warning_not_raise(self) -> None:
        """ReadTimeout must be caught; the session must continue (no exception propagates)."""
        api = _make_api()

        async def _timeout_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            raise httpx.ReadTimeout("server took too long", request=None)
            yield  # make it an async generator

        api.agent_query_stream = _timeout_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Must not raise
        await session._handle_query("What's my schedule?")

    @pytest.mark.asyncio
    async def test_handle_query_connect_timeout_shows_warning_not_raise(self) -> None:
        """ConnectTimeout must be caught; the session must continue (no exception propagates)."""
        api = _make_api()

        async def _timeout_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            raise httpx.ConnectTimeout("connection timed out", request=None)
            yield  # make it an async generator

        api.agent_query_stream = _timeout_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        # Must not raise
        await session._handle_query("What's my schedule?")

    @pytest.mark.asyncio
    async def test_handle_query_timeout_session_continues(self) -> None:
        """After a timeout the session loop is still alive — subsequent queries work."""
        api = _make_api()
        call_count = 0

        async def _flaky_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("timed out", request=None)
                yield  # make it an async generator
            yield "token", {"text": "3 tasks pending."}
            yield "done", {"session_id": "sid", "iterations": 1, "tools_used": []}

        api.agent_query_stream = _flaky_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        await session._handle_query("first question")   # times out — must not raise
        await session._handle_query("second question")  # succeeds

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_handle_query_timeout_does_not_call_api_twice(self) -> None:
        """A timeout must not trigger a retry — stream is called exactly once."""
        api = _make_api()
        call_count = 0

        async def _timeout_stream(question: str, session_id: Optional[str] = None) -> AsyncGenerator[Tuple[str, Any], None]:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("timed out", request=None)
            yield  # make it an async generator

        api.agent_query_stream = _timeout_stream
        session = ChatSession(api=api, config=_make_config())
        session._prompt_session = None

        await session._handle_query("heavy question")

        assert call_count == 1
