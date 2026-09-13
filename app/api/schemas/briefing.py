"""Schemas for the briefing and agent endpoints."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BriefingResponse(BaseModel):
    """Response from GET /briefing/{user_id}."""

    agenda: List[Dict[str, Any]] = Field(default_factory=list)
    pending_commitments: List[Dict[str, Any]] = Field(default_factory=list)
    overdue_commitments: List[Dict[str, Any]] = Field(default_factory=list)
    contextual_alerts: List[str] = Field(default_factory=list)
    briefing_text: str = ""
    generated_at: str


class ScheduleRequest(BaseModel):
    """Request body for POST /briefing/{user_id}/schedule."""

    hour: int = Field(default=7, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "UTC"


class ScheduleResponse(BaseModel):
    """Response from POST /briefing/{user_id}/schedule."""

    scheduled: bool
    message: str


class AgentQueryRequest(BaseModel):
    """Request body for POST /agent/query."""

    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None


AgentStreamRequest = AgentQueryRequest


class AgentQueryResponse(BaseModel):
    """Response from POST /agent/query."""

    answer: str
    tools_used: List[str]
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    query: str
    session_id: str = ""
    iterations: int = 0
    # "end_turn" | "interrupt" | "error" (app.api.schemas.stream.StopReason).
    # A caller of this non-streaming endpoint with enable_generative_ui on
    # must check this — a request_user_input call ends the turn early, and
    # `answer` alone doesn't say so.
    stop_reason: str = "end_turn"
    awaiting: List[str] = Field(default_factory=list)
