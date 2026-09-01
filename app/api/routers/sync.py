"""Sync management endpoints — configure, monitor, and trigger server-side syncs."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.sync import (
    SyncConfigureRequest,
    SyncIntegrationStatus,
    SyncStatusResponse,
    SyncTriggerResponse,
)
from app.models.integration import Integration

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return sync status for all integrations and scheduler state."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user_id,
            Integration.is_active == True,  # noqa: E712
        )
    )
    integrations = result.scalars().all()

    # Check if scheduler is running
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    scheduler_active = scheduler is not None and scheduler.is_running

    # Build per-integration status
    job_info = {}
    if scheduler:
        for job in scheduler.get_job_info():
            job_info[job["job_id"]] = job.get("next_run")

    statuses = []
    for integ in integrations:
        job_id = "sync_{0}".format(integ.id)
        next_run = job_info.get(job_id)
        statuses.append(SyncIntegrationStatus(
            integration_id=str(integ.id),
            platform=integ.platform.value,
            sync_enabled=integ.sync_enabled,
            sync_interval_minutes=integ.sync_interval_minutes,
            last_sync_at=integ.last_sync_at.isoformat() if integ.last_sync_at else None,
            last_sync_status=integ.last_sync_status,
            last_sync_error=integ.last_sync_error,
            next_scheduled_run=next_run,
        ))

    return {
        "scheduler_active": scheduler_active,
        "integrations": statuses,
    }


@router.post("/configure", response_model=SyncIntegrationStatus)
async def configure_sync(
    body: SyncConfigureRequest,
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SyncIntegrationStatus:
    """Update sync configuration for a platform integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user_id,
            Integration.platform == body.platform,
            Integration.is_active == True,  # noqa: E712
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active {0} integration found".format(body.platform),
        )

    integration.sync_enabled = body.enabled
    integration.sync_interval_minutes = body.interval_minutes
    await db.flush()

    # Reschedule the job if scheduler is running
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    if scheduler and scheduler.is_running:
        scheduler.reschedule_job(integration)

    logger.info(
        "Sync configured: platform=%s enabled=%s interval=%dm",
        body.platform, body.enabled, body.interval_minutes,
    )

    return SyncIntegrationStatus(
        integration_id=str(integration.id),
        platform=integration.platform.value,
        sync_enabled=integration.sync_enabled,
        sync_interval_minutes=integration.sync_interval_minutes,
        last_sync_at=integration.last_sync_at.isoformat() if integration.last_sync_at else None,
        last_sync_status=integration.last_sync_status,
        last_sync_error=integration.last_sync_error,
        next_scheduled_run=None,
    )


@router.post("/trigger/{platform}", response_model=SyncTriggerResponse)
async def trigger_sync(
    platform: str,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force an immediate sync for a platform. Updates sync tracking columns."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user_id,
            Integration.platform == platform,
            Integration.is_active == True,  # noqa: E712
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active {0} integration found".format(platform),
        )

    try:
        from app.api.routers.ingestion import _CONNECTORS
        from app.services.ingestion.pipeline import IngestionPipeline
        from app.services import integration_service

        if platform not in _CONNECTORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported platform: {0}".format(platform),
            )

        from app.services.ingestion.embedder import Embedder
        from app.services.token_refresh import ensure_fresh_token

        token = await ensure_fresh_token(integration, db)
        connector = _CONNECTORS[platform]()  # type: ignore[abstract]
        items = await connector.fetch_items(
            access_token=token,
            since=integration.last_sync_at,
        )

        from app.core.config import get_settings
        settings = get_settings()
        pipeline = IngestionPipeline(embedder=Embedder(api_key=settings.openai_api_key))
        ingest_result = await pipeline.ingest_batch(
            db=db,
            user_id=current_user_id,
            items=[item.to_dict() for item in items],
            source=platform,
        )

        integration.last_sync_at = datetime.now(timezone.utc)
        integration.last_sync_status = "success"
        integration.last_sync_error = None
        await db.flush()

        return {
            "platform": platform,
            "status": "success",
            "documents_created": ingest_result.documents_created,
            "documents_updated": ingest_result.documents_updated,
        }

    except HTTPException:
        raise
    except Exception as e:
        integration.last_sync_status = "error"
        integration.last_sync_error = str(e)[:500]
        integration.last_sync_at = datetime.now(timezone.utc)
        await db.flush()

        logger.exception("Manual sync trigger failed: platform=%s", platform)
        return {
            "platform": platform,
            "status": "error",
            "error": "Sync failed — check server logs for details",
        }
