"""Voice endpoints: STT transcription and TTS synthesis."""
import logging
import uuid
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user_id
from app.api.schemas.voice import SpeakRequest, TranscribeResponse
from app.core.config import get_settings
from app.services.voice.transcriber import WhisperTranscriber
from app.services.voice import tts as tts_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/mpeg",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "application/octet-stream",
}


@lru_cache(maxsize=1)
def _get_transcriber() -> WhisperTranscriber:
    settings = get_settings()
    return WhisperTranscriber(
        mode=settings.stt_mode,
        model_name=settings.whisper_model,
        openai_api_key=settings.openai_api_key,
    )


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile,
    _: uuid.UUID = Depends(get_current_user_id),
) -> TranscribeResponse:
    """Transcribe uploaded audio to text using Whisper."""
    settings = get_settings()
    max_bytes = settings.voice_max_audio_mb * 1024 * 1024

    audio_bytes = await file.read()

    if len(audio_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Audio file is empty")

    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file exceeds {settings.voice_max_audio_mb}MB limit",
        )

    transcriber = _get_transcriber()
    try:
        result = await transcriber.transcribe(audio_bytes, filename=file.filename or "audio.webm")
    except RuntimeError as e:
        logger.error("Transcription failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Transcription service unavailable")

    return result


@router.post("/speak")
async def speak_text(
    data: SpeakRequest,
    _: uuid.UUID = Depends(get_current_user_id),
) -> StreamingResponse:
    """Convert text to speech and stream MP3 audio."""
    settings = get_settings()

    valid_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    if data.voice not in valid_voices:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid voice '{data.voice}'. Valid options: {sorted(valid_voices)}",
        )

    try:
        audio_stream = tts_service.synthesize(
            text=data.text,
            voice=data.voice,
            model=settings.tts_model,
            api_key=settings.openai_api_key,
        )
    except Exception as e:
        logger.error("TTS failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TTS service unavailable")

    return StreamingResponse(
        audio_stream,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )
