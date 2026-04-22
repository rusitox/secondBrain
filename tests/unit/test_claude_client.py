"""Unit tests for the multi-provider LLM client."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.claude_client import (
    ClaudeClient,
    LLMClient,
    DEFAULT_MODEL,
    MAX_RETRIES,
    MAX_TOKENS,
    _parse_provider,
)


class TestParseProvider:
    """Tests for the provider/model parser."""

    def test_anthropic_prefix(self) -> None:
        assert _parse_provider("anthropic/claude-haiku-4-5-20251001") == (
            "anthropic", "claude-haiku-4-5-20251001"
        )

    def test_openai_prefix(self) -> None:
        assert _parse_provider("openai/gpt-4o-mini") == (
            "openai", "gpt-4o-mini"
        )

    def test_no_prefix_defaults_anthropic(self) -> None:
        assert _parse_provider("claude-haiku-4-5-20251001") == (
            "anthropic", "claude-haiku-4-5-20251001"
        )

    def test_case_insensitive_provider(self) -> None:
        assert _parse_provider("OpenAI/gpt-4o-mini") == (
            "openai", "gpt-4o-mini"
        )


class TestLLMClientInit:
    """Tests for LLMClient initialization."""

    def test_default_model(self) -> None:
        client = LLMClient(api_key="test-key")
        assert client._model == DEFAULT_MODEL
        assert client._provider == "anthropic"

    def test_openai_model(self) -> None:
        client = LLMClient(api_key="test-key", model="openai/gpt-4o-mini")
        assert client._provider == "openai"
        assert client._model_id == "gpt-4o-mini"

    def test_custom_max_tokens(self) -> None:
        client = LLMClient(api_key="test-key", max_tokens=4096)
        assert client._max_tokens == 4096

    def test_backward_compat_alias(self) -> None:
        assert ClaudeClient is LLMClient


def _make_anthropic_response(text: str) -> MagicMock:
    """Create a mock Anthropic response."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_openai_response(text: str) -> MagicMock:
    """Create a mock OpenAI response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def mock_anthropic():
    """Patch AsyncAnthropic and return the mock instance."""
    with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_openai():
    """Patch AsyncOpenAI and return the mock instance."""
    with patch("app.services.llm.claude_client.AsyncOpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestAnthropicGenerate:
    """Tests for generation via Anthropic provider."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, mock_anthropic: MagicMock) -> None:
        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_anthropic_response("Hello from Claude")
        )
        client = LLMClient(api_key="test-key", model="anthropic/claude-haiku-4-5-20251001")
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
        client = LLMClient(api_key="test-key")
        result = await client.generate(system_prompt="sys", user_message="msg")
        assert result == ""

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, mock_anthropic: MagicMock) -> None:
        from anthropic import RateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        rate_err = RateLimitError(
            message="Rate limited", response=mock_response, body=None,
        )
        mock_anthropic.messages.create = AsyncMock(
            side_effect=[rate_err, _make_anthropic_response("OK after retry")]
        )
        client = LLMClient(api_key="test-key")
        result = await client.generate(system_prompt="sys", user_message="msg")
        assert result == "OK after retry"
        assert mock_anthropic.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_temperature_passed(self, mock_anthropic: MagicMock) -> None:
        mock_anthropic.messages.create = AsyncMock(
            return_value=_make_anthropic_response("ok")
        )
        client = LLMClient(api_key="test-key")
        await client.generate(
            system_prompt="sys", user_message="msg", temperature=0.7,
        )
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7


class TestOpenAIGenerate:
    """Tests for generation via OpenAI provider."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, mock_openai: MagicMock) -> None:
        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("Hello from GPT")
        )
        client = LLMClient(api_key="test-key", model="openai/gpt-4o-mini")
        result = await client.generate(
            system_prompt="You are helpful.",
            user_message="Hi",
        )
        assert result == "Hello from GPT"
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, mock_openai: MagicMock) -> None:
        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("ok")
        )
        client = LLMClient(
            api_key="test-key", model="openai/gpt-4o-mini", max_tokens=1024,
        )
        await client.generate(
            system_prompt="sys", user_message="msg", temperature=0.7,
        )
        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["temperature"] == 0.7
        messages = call_kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "sys"}
        assert messages[1] == {"role": "user", "content": "msg"}

    @pytest.mark.asyncio
    async def test_empty_content(self, mock_openai: MagicMock) -> None:
        resp = _make_openai_response("")
        resp.choices[0].message.content = None
        mock_openai.chat.completions.create = AsyncMock(return_value=resp)
        client = LLMClient(api_key="test-key", model="openai/gpt-4o-mini")
        result = await client.generate(system_prompt="sys", user_message="msg")
        assert result == ""
