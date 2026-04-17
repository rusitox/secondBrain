"""Schemas for identity (persona, tone, heuristics) endpoints."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class IdentityCreate(BaseModel):
    persona_description: str = ""
    tone_guidelines: str = ""
    heuristics: Dict[str, Any] = {}


class IdentityUpdate(BaseModel):
    persona_description: Optional[str] = None
    tone_guidelines: Optional[str] = None
    heuristics: Optional[Dict[str, Any]] = None


class IdentityRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    persona_description: str
    tone_guidelines: str
    heuristics: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserStats(BaseModel):
    documents_total: int
    commitments_pending: int
    commitments_overdue: int
    integrations_active: int
    integrations_total: int
    last_sync: Optional[datetime] = None
