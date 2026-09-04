"""Unit tests for WhisperTranscriber."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.voice.transcriber import WhisperTranscriber


class TestWhisperTranscriberAPI:
    @pytest.mark.asyncio
    async def test_api_mode_calls_openai(self) -> None:
        transcriber = WhisperTranscriber(mode="api", openai_api_key="test-key")

        mock_response = MagicMock()
        mock_response.text = "hello world"
        mock_response.duration = 2.5
        mock_response.language = "es"

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

            result = await transcriber.transcribe(b"fake-audio", "audio.webm")

        assert result.transcript == "hello world"
        assert result.language == "es"
        assert result.duration_seconds == 2.5

    @pytest.mark.asyncio
    async def test_empty_audio_raises_no_error(self) -> None:
        """The transcriber itself doesn't check size — the router does."""
        transcriber = WhisperTranscriber(mode="api", openai_api_key="test-key")
        mock_response = MagicMock()
        mock_response.text = ""
        mock_response.duration = 0.0

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
            result = await transcriber.transcribe(b"", "audio.webm")

        assert result.transcript == ""
