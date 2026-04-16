"""Unit tests for the Claude client wrapper."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.claude_client import (
    ClaudeClient,
    DEFAULT_MODEL,
    MAX_RETRIES,
    MAX_TOKENS,
)


@pytest.fixture
def mock_anthropic():
    """Patch AsyncAnthropic and return the mock."""
    with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_response(text: str) -> MagicMock:
    """Create a mock Anthropic response."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestClaudeClientInit:
    """Tests for ClaudeClient initialization."""

    def test_default_model(self, mock_anthropic: MagicMock) -> None:
        client = ClaudeClient(api_key="test-key")
        assert client._model == DEFAULT_MODEL

    def test_custom_model(self, mock_anthropic: MagicMock) -> None:
        client = ClaudeClient(api_key="test-key", model="claude-opus-4-20250514")
        assert client._model == "claude-opus-4-20250514"

    def test_custom_max_tokens(self, mock_anthropic: MagicMock) -> None:
        client = ClaudeClient(api_key="test-key", max_tokens=4096)
        assert client._max_tokens == 4096


class TestClaudeClientGenerate:
    """Tests for the generate method."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, mock_anthropic: MagicMock) -> None:
        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_response("Hello from Claude")
        )
        client = ClaudeClient(api_key="test-key")
        result = await client.generate(
            system_prompt="You are helpful.",
            user_message="Hi",
        )
        assert result == "Hello from Claude"
        mock_anthropic.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_content(self, mock_anthropic: MagicMock) -> None:
        resp = MagicMock()
        resp.content = []
        mock_anthropic.messages.create = AsyncMock(return_value=resp)
        client = ClaudeClient(api_key="test-key")
        result = await client.generate(
            system_prompt="sys",
            user_message="msg",
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, mock_anthropic: MagicMock) -> None:
        from anthropic import RateLimitError
        from unittest.mock import PropertyMock

        # Build a proper RateLimitError
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        rate_err = RateLimitError(
            message="Rate limited",
            response=mock_response,
            body=None,
        )

        mock_anthropic.messages.create = AsyncMock(
            side_effect=[rate_err, _make_response("OK after retry")]
        )
        client = ClaudeClient(api_key="test-key")
        result = await client.generate(
            system_prompt="sys",
            user_message="msg",
        )
        assert result == "OK after retry"
        assert mock_anthropic.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_server_error_retry(self, mock_anthropic: MagicMock) -> None:
        from anthropic import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}
        server_err = APIStatusError(
            message="Internal error",
            response=mock_response,
            body=None,
        )

        mock_anthropic.messages.create = AsyncMock(
            side_effect=[server_err, _make_response("OK after retry")]
        )
        client = ClaudeClient(api_key="test-key")
        result = await client.generate(
            system_prompt="sys",
            user_message="msg",
        )
        assert result == "OK after retry"

    @pytest.mark.asyncio
    async def test_client_error_raises_immediately(self, mock_anthropic: MagicMock) -> None:
        from anthropic import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.headers = {}
        client_err = APIStatusError(
            message="Bad request",
            response=mock_response,
            body=None,
        )

        mock_anthropic.messages.create = AsyncMock(side_effect=client_err)
        client = ClaudeClient(api_key="test-key")
        with pytest.raises(APIStatusError):
            await client.generate(
                system_prompt="sys",
                user_message="msg",
            )
        # Should NOT retry for 4xx
        assert mock_anthropic.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, mock_anthropic: MagicMock) -> None:
        from anthropic import RateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        rate_err = RateLimitError(
            message="Rate limited",
            response=mock_response,
            body=None,
        )

        mock_anthropic.messages.create = AsyncMock(
            side_effect=[rate_err] * MAX_RETRIES
        )
        client = ClaudeClient(api_key="test-key")
        with pytest.raises(RateLimitError):
            await client.generate(
                system_prompt="sys",
                user_message="msg",
            )
        assert mock_anthropic.messages.create.call_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_temperature_passed(self, mock_anthropic: MagicMock) -> None:
        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_response("ok")
        )
        client = ClaudeClient(api_key="test-key")
        await client.generate(
            system_prompt="sys",
            user_message="msg",
            temperature=0.7,
        )
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7
