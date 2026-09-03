"""Schemas for voice endpoints."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

VoiceName = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class TranscribeResponse(BaseModel):
    transcript: str
    language: str
    duration_seconds: Optional[float] = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: VoiceName = "nova"
