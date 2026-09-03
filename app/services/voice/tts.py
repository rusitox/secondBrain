"""Text-to-speech service using OpenAI TTS API."""
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


async def synthesize(
    text: str,
    voice: str = "nova",
    model: str = "tts-1",
    api_key: str = "",
) -> AsyncIterator[bytes]:
    """Stream MP3 audio bytes from OpenAI TTS."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    async with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,  # type: ignore[arg-type]
        input=text,
        response_format="mp3",
    ) as response:
        async for chunk in response.iter_bytes(chunk_size=4096):
            yield chunk
