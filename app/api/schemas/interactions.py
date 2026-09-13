"""Response shapes for the read side of the generative UI protocol.

Fase 2/3 built the write side (POST .../answer, POST .../actions/{id}/
approve|reject) but never gave the client a way to fetch WHAT it's being
asked to answer or approve — /agent/stream's `done` event only carries an
opaque `awaiting: [interaction_id, ...]` list, and a `propose_action` tool
call never told the client an action_id existed at all. These two GETs
close that gap: the client discovers an id (via `done.awaiting` for
interactions, via the `action_proposed` SSE event for actions — see
app/api/schemas/stream.py) and fetches the full, validated spec/artifact
to render.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class InteractionDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    spec: Dict[str, Any]  # a validated app.api.schemas.ui_protocol.UIRequest
    answer: Optional[Dict[str, Any]] = None
    expires_at: datetime


class ProposedActionDetailResponse(BaseModel):
    id: uuid.UUID
    action_type: str
    status: str
    risk: str
    artifact: Dict[str, Any]  # a validated app.api.schemas.ui_protocol.Artifact
    payload_sha256: str  # echo back on POST .../approve to bind approval to these exact bytes
    expires_at: datetime
    error: Optional[str] = None
