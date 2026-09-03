"""Schemas for voice endpoints."""
from typing import Optional

from pydantic import BaseModel, Field


class TranscribeResponse(BaseModel):
    transcript: str
    language: str
    duration_seconds: Optional[float] = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: str = Field(default="nova")
