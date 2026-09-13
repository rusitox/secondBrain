"""Text-to-speech service using OpenAI TTS API."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# The classic tts-1/tts-1-hd models auto-detect language per request with
# no way to pin it — a short, isolated sentence fragment (this app streams
# TTS sentence-by-sentence) with an ambiguous or English word/acronym in
# it can get mis-detected and synthesized in the wrong language entirely.
# gpt-4o-mini-tts is the model that accepts `instructions` to steer this.
_MODELS_SUPPORTING_INSTRUCTIONS = {"gpt-4o-mini-tts"}

_SPANISH_INSTRUCTIONS = (
    "Hablá siempre en español rioplatense (Argentina). Nunca cambies de "
    "idioma, incluso si el texto tiene una palabra, sigla o nombre propio "
    "en inglés — pronuncialo con acento español."
)


async def synthesize(
    text: str,
    voice: str = "nova",
    model: str = "gpt-4o-mini-tts",
    api_key: str = "",
) -> bytes:
    """Return MP3 audio bytes from OpenAI TTS."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    if model in _MODELS_SUPPORTING_INSTRUCTIONS:
        response = await client.audio.speech.create(
            model=model,
            voice=voice,  # type: ignore[arg-type]
            input=text,
            response_format="mp3",
            instructions=_SPANISH_INSTRUCTIONS,
        )
    else:
        response = await client.audio.speech.create(
            model=model,
            voice=voice,  # type: ignore[arg-type]
            input=text,
            response_format="mp3",
        )
    return response.content
