"""GET /systems/status — the MAREA header's connected-systems semaphore.

Aggregates /sync/status (per-integration ingestion health) and
/knowledge/status (per-source processing backlog) into one list the client
renders as-is, with no hardcoded source names on either side: a source
shows up here the moment a user connects it (an active Integration row)
or it has any document backlog, and disappears when neither is true
anymore. See app/api/routers/systems.py for the health rules.
"""
from typing import List, Optional

from pydantic import BaseModel


class SystemStatusItem(BaseModel):
    source: str  # Platform value, e.g. "outlook", "slack", "fathom", "notion", "teams"
    health: str  # "ok" | "stale" | "error" | "disabled" | "external"
    detail: Optional[str] = None  # human-readable explanation, e.g. the sync error
    sync_enabled: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    next_scheduled_run: Optional[str] = None
    pending_documents: int = 0


class SystemsStatusResponse(BaseModel):
    systems: List[SystemStatusItem]
    sync_scheduler_active: bool
    knowledge_scheduler_active: bool
