"""Speech-to-text service using Whisper (local or OpenAI API)."""
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from app.api.schemas.voice import TranscribeResponse

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    """STT service. Supports local Whisper model or OpenAI Whisper API."""

    def __init__(self, mode: str = "api", model_name: str = "base", openai_api_key: str = "") -> None:
        self._mode = mode
        self._model_name = model_name
        self._openai_api_key = openai_api_key
        self._local_model: Optional[object] = None  # loaded lazily

    def _load_local_model(self) -> object:
        if self._local_model is None:
            try:
                import whisper  # type: ignore[import]
                logger.info("Loading Whisper model '%s'...", self._model_name)
                self._local_model = whisper.load_model(self._model_name)
                logger.info("Whisper model loaded.")
            except ImportError:
                raise RuntimeError(
                    "openai-whisper is not installed. Run: pip install openai-whisper"
                )
        return self._local_model

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> TranscribeResponse:
        if self._mode == "local":
            return await self._transcribe_local(audio_bytes)
        return await self._transcribe_api(audio_bytes, filename)

    async def _transcribe_local(self, audio_bytes: bytes) -> TranscribeResponse:
        import asyncio

        def _run() -> TranscribeResponse:
            model = self._load_local_model()
            suffix = ".webm"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                tmp_path = Path(f.name)
            try:
                result = model.transcribe(str(tmp_path), language="es")  # type: ignore[union-attr]
                return TranscribeResponse(
                    transcript=result.get("text", "").strip(),
                    language=result.get("language", "es"),
                    duration_seconds=None,
                )
            finally:
                tmp_path.unlink(missing_ok=True)

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _transcribe_api(self, audio_bytes: bytes, filename: str) -> TranscribeResponse:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._openai_api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="es",
            response_format="verbose_json",
        )
        duration: Optional[float] = None
        if hasattr(response, "duration"):
            duration = float(response.duration)
        transcript = response.text if hasattr(response, "text") else str(response)
        return TranscribeResponse(
            transcript=transcript.strip(),
            language="es",
            duration_seconds=duration,
        )
