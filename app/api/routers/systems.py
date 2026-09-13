"""Aggregated connected-systems status for MAREA's header semaphore.

Merges two things that already exist (app/api/routers/sync.py's per-
integration ingestion health, app/services/agent/knowledge/store.py's
per-source processing backlog) into one list, keyed by whatever source
names actually show up in either — never a hardcoded platform list, so a
newly connected source appears here on its own the moment its Integration
row exists, exactly what Mariano asked for.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.systems import SystemsStatusResponse, SystemStatusItem
from app.core.config import Settings, get_settings
from app.models.integration import Integration
from app.services.agent.knowledge import store as knowledge_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/systems", tags=["systems"])

# A sync is considered stale once it's older than this many multiples of
# the integration's own configured interval — not a fixed wall-clock
# window, since integrations can be configured anywhere from 5 minutes to
# 24 hours apart.
STALE_INTERVAL_MULTIPLIER = 2
# Floor under that multiplier so a 5-minute-interval integration doesn't
# flash yellow over an ordinary few-minute scheduling jitter.
STALE_MINIMUM_MINUTES = 60
# A source with more unprocessed documents than this looks "behind" even
# if its most recent sync itself succeeded — the ingestion is keeping up,
# the knowledge extraction over it isn't.
BACKLOG_STALE_THRESHOLD = 200

# Fathom has no public REST API (see app/services/connectors/fathom.py —
# fetch_items always raises NotImplementedError) and is synced out-of-band
# via a manual script, never by the scheduler (app/services/sync/
# scheduler.py explicitly skips it). Its health is never "error" here
# regardless of what a stray manual /sync/trigger/fathom call may have
# left in last_sync_status — that's a known false signal for this one
# platform, not a real failure the semaphore should alarm on.
EXTERNAL_SYNC_PLATFORMS = {"fathom"}


def _apply_backlog_downgrade(health: str, detail: Optional[str], pending: int) -> "tuple[str, Optional[str]]":
    """A source with more unprocessed documents than BACKLOG_STALE_THRESHOLD
    looks "behind" even if its most recent sync succeeded (or it has no
    sync of its own at all, e.g. a connector-less source like the I+D
    agent) — shared by both branches below so a backlog-only source can't
    silently stay "ok" forever just because it never had an Integration
    row to fail health checks against."""
    if health == "ok" and pending > BACKLOG_STALE_THRESHOLD:
        return "stale", f"{pending} documentos pendientes de procesar"
    return health, detail


def _integration_health(integ: Integration, now: datetime) -> "tuple[str, Optional[str]]":
    if integ.platform.value in EXTERNAL_SYNC_PLATFORMS:
        return "external", "Sincronización externa (script manual, fuera del scheduler)"
    if not integ.sync_enabled:
        return "disabled", None
    if integ.last_sync_status == "error":
        return "error", integ.last_sync_error
    if integ.last_sync_at is None:
        return "stale", "Nunca se sincronizó"
    last_sync_at = integ.last_sync_at
    if last_sync_at.tzinfo is None:
        last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
    stale_after = timedelta(
        minutes=max(integ.sync_interval_minutes * STALE_INTERVAL_MULTIPLIER, STALE_MINIMUM_MINUTES)
    )
    if now - last_sync_at > stale_after:
        return "stale", "Última sincronización hace más de lo esperado"
    return "ok", None


@router.get("/status", response_model=SystemsStatusResponse)
async def get_systems_status(
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Per-source sync + knowledge-processing health, for the MAREA
    header's traffic light. Every source the user has ever connected or
    has any document backlog for shows up — nothing hardcoded."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user_id,
            Integration.is_active == True,  # noqa: E712
        )
    )
    integrations = result.scalars().all()

    sync_scheduler = getattr(request.app.state, "sync_scheduler", None)
    sync_scheduler_active = sync_scheduler is not None and sync_scheduler.is_running
    job_next_run: Dict[str, Optional[str]] = {}
    if sync_scheduler:
        for job in sync_scheduler.get_job_info():
            job_next_run[job["job_id"]] = job.get("next_run")

    knowledge_stats = await knowledge_store.get_knowledge_stats(db, current_user_id)
    pending_by_source: Dict[str, int] = knowledge_stats.get("pending_documents_by_source", {})

    knowledge_scheduler = getattr(request.app.state, "knowledge_scheduler", None)
    knowledge_scheduler_active = knowledge_scheduler is not None and knowledge_scheduler.is_running

    items: Dict[str, SystemStatusItem] = {}
    for integ in integrations:
        source = integ.platform.value
        health, detail = _integration_health(integ, now)
        pending = pending_by_source.get(source, 0)
        health, detail = _apply_backlog_downgrade(health, detail, pending)
        items[source] = SystemStatusItem(
            source=source,
            health=health,
            detail=detail,
            sync_enabled=integ.sync_enabled,
            last_sync_at=integ.last_sync_at.isoformat() if integ.last_sync_at else None,
            last_sync_status=integ.last_sync_status,
            next_scheduled_run=job_next_run.get(f"sync_{integ.id}"),
            pending_documents=pending,
        )

    # A source can carry a document backlog without an active Integration
    # row (e.g. the I+D/R&D agent's MCP-backed source, which was never a
    # connector to begin with) — surface it too, just without sync-side
    # fields that don't apply to it.
    for source, pending in pending_by_source.items():
        if source in items:
            continue
        health = "external" if source in EXTERNAL_SYNC_PLATFORMS else "ok"
        health, detail = _apply_backlog_downgrade(health, None, pending)
        items[source] = SystemStatusItem(
            source=source,
            health=health,
            detail=detail,
            sync_enabled=False,
            pending_documents=pending,
        )

    return {
        "systems": sorted(items.values(), key=lambda s: s.source),
        "sync_scheduler_active": sync_scheduler_active,
        "knowledge_scheduler_active": knowledge_scheduler_active,
    }
