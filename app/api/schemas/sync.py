from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SyncConfigureRequest(BaseModel):
    platform: str
    enabled: bool = True
    interval_minutes: int = Field(default=30, ge=5, le=1440)


class SyncIntegrationStatus(BaseModel):
    integration_id: str
    platform: str
    sync_enabled: bool
    sync_interval_minutes: int
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    last_sync_error: Optional[str] = None
    next_scheduled_run: Optional[str] = None


class SyncStatusResponse(BaseModel):
    scheduler_active: bool
    integrations: List[SyncIntegrationStatus]


class SyncTriggerResponse(BaseModel):
    platform: str
    status: str
    documents_created: int = 0
    documents_updated: int = 0
    error: Optional[str] = None
