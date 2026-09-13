"""Unit tests for app.services.voice.tts.synthesize — the Spanish-language
steering added after MAREA's TTS was observed switching to English mid
response (tts-1/tts-1-hd have no language-pinning parameter at all)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.voice.tts import synthesize


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_passes_instructions_for_gpt_4o_mini_tts(self) -> None:
        mock_response = MagicMock(content=b"audio-bytes")
        mock_create = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.audio.speech.create = mock_create

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            result = await synthesize(text="hola", model="gpt-4o-mini-tts", api_key="k")

        assert result == b"audio-bytes"
        assert "instructions" in mock_create.call_args.kwargs
        assert "español" in mock_create.call_args.kwargs["instructions"]

    @pytest.mark.asyncio
    async def test_omits_instructions_for_tts_1(self) -> None:
        """tts-1/tts-1-hd don't accept `instructions` — passing it would
        be an API error, so it must only be sent for models that support it."""
        mock_response = MagicMock(content=b"audio-bytes")
        mock_create = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.audio.speech.create = mock_create

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            await synthesize(text="hola", model="tts-1", api_key="k")

        assert "instructions" not in mock_create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_default_model_supports_instructions(self) -> None:
        """The default model must be one that actually lets us pin the
        language — otherwise this fix silently does nothing out of the box."""
        mock_response = MagicMock(content=b"audio-bytes")
        mock_create = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.audio.speech.create = mock_create

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            await synthesize(text="hola", api_key="k")

        assert "instructions" in mock_create.call_args.kwargs
