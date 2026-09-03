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

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        language: Optional[str] = None,
    ) -> TranscribeResponse:
        if self._mode == "local":
            return await self._transcribe_local(audio_bytes, filename=filename, language=language)
        return await self._transcribe_api(audio_bytes, filename, language=language)

    async def _transcribe_local(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        language: Optional[str] = None,
    ) -> TranscribeResponse:
        import asyncio

        def _run() -> TranscribeResponse:
            model = self._load_local_model()
            suffix = Path(filename).suffix if Path(filename).suffix else ".webm"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                tmp_path = Path(f.name)
            try:
                kwargs = {"language": language} if language is not None else {}
                result = model.transcribe(str(tmp_path), **kwargs)  # type: ignore[union-attr]
                detected_lang = result.get("language", language or "")
                return TranscribeResponse(
                    transcript=result.get("text", "").strip(),
                    language=detected_lang,
                    duration_seconds=None,
                )
            finally:
                tmp_path.unlink(missing_ok=True)

        return await asyncio.get_running_loop().run_in_executor(None, _run)

    async def _transcribe_api(
        self,
        audio_bytes: bytes,
        filename: str,
        language: Optional[str] = None,
    ) -> TranscribeResponse:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._openai_api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        kwargs = {
            "model": "whisper-1",
            "file": audio_file,
            "response_format": "verbose_json",
        }
        if language is not None:
            kwargs["language"] = language

        response = await client.audio.transcriptions.create(**kwargs)  # type: ignore[arg-type]
        detected_lang: str = ""
        if hasattr(response, "language"):
            detected_lang = str(response.language)
        duration: Optional[float] = None
        if hasattr(response, "duration"):
            duration = float(response.duration)
        transcript = response.text if hasattr(response, "text") else str(response)
        return TranscribeResponse(
            transcript=transcript.strip(),
            language=detected_lang or language or "",
            duration_seconds=duration,
        )
