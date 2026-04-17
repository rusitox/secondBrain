"""Schemas for ingestion API endpoints."""
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class IngestRawRequest(BaseModel):
    user_id: uuid.UUID
    content: str
    source: str = Field(max_length=20)
    source_id: str = ""
    metadata_: Dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = {"populate_by_name": True}


class IngestResult(BaseModel):
    documents_created: int
    documents_updated: int
    documents_skipped: int
    chunks_total: int
    commitments_detected: int = 0


class SyncStatusResponse(BaseModel):
    integration_id: uuid.UUID
    platform: str
    is_active: bool
    last_sync_at: Optional[str]
