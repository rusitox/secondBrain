"""Text-to-speech service using OpenAI TTS API."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def synthesize(
    text: str,
    voice: str = "nova",
    model: str = "tts-1",
    api_key: str = "",
) -> bytes:
    """Return MP3 audio bytes from OpenAI TTS."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    response = await client.audio.speech.create(
        model=model,
        voice=voice,  # type: ignore[arg-type]
        input=text,
        response_format="mp3",
    )
    return response.content
