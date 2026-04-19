"""Server-side sync scheduler using APScheduler.

Runs periodic platform syncs so data stays up-to-date even when no CLI
is connected. Reuses the ingestion pipeline internally (no HTTP round-trip).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.integration import Integration

logger = logging.getLogger(__name__)

# APScheduler is optional — import safely
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.info("APScheduler not installed — sync scheduling disabled")


class SyncScheduler:
    """Manages periodic sync jobs for all active integrations."""

    def __init__(self) -> None:
        self._scheduler: Optional[object] = None
        self._running = False
        if HAS_APSCHEDULER:
            self._scheduler = AsyncIOScheduler()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_available(self) -> bool:
        return HAS_APSCHEDULER

    async def start(self) -> None:
        """Start the scheduler and load jobs for all active integrations."""
        if self._running:
            return
        if not self._scheduler or not HAS_APSCHEDULER:
            logger.warning("Cannot start sync scheduler — APScheduler not available")
            return

        self._scheduler.start()  # type: ignore[attr-defined]
        self._running = True
        logger.info("Sync scheduler started")

        # Load existing integrations and schedule jobs
        await self._load_jobs()

    async def shutdown(self) -> None:
        """Shutdown the scheduler gracefully."""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            self._running = False
            logger.info("Sync scheduler stopped")

    async def _load_jobs(self) -> None:
        """Query all active integrations and schedule sync jobs."""
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Integration).where(
                    Integration.is_active == True,  # noqa: E712
                    Integration.sync_enabled == True,  # noqa: E712
                )
            )
            integrations = result.scalars().all()

            for integ in integrations:
                self._schedule_job(integ)

            logger.info("Loaded %d sync jobs", len(integrations))

    def _schedule_job(self, integration: Integration) -> None:
        """Schedule a sync job for a single integration."""
        if not self._scheduler or not HAS_APSCHEDULER:
            return

        job_id = "sync_{0}".format(integration.id)
        interval = max(integration.sync_interval_minutes or 30, 5)  # minimum 5 minutes

        trigger = IntervalTrigger(minutes=interval)  # type: ignore[possibly-undefined]
        self._scheduler.add_job(  # type: ignore[attr-defined]
            self._run_sync,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs={"integration_id": str(integration.id), "user_id": str(integration.user_id)},
        )
        logger.info(
            "Scheduled sync job %s: platform=%s interval=%dm",
            job_id, integration.platform.value, interval,
        )

    def remove_job(self, integration_id: str) -> None:
        """Remove a scheduled sync job."""
        if not self._scheduler or not HAS_APSCHEDULER:
            return
        job_id = "sync_{0}".format(integration_id)
        try:
            self._scheduler.remove_job(job_id)  # type: ignore[attr-defined]
            logger.info("Removed sync job %s", job_id)
        except (LookupError, KeyError):
            pass  # Job may not exist

    def reschedule_job(self, integration: Integration) -> None:
        """Remove and re-add a job with updated interval."""
        self.remove_job(str(integration.id))
        if integration.is_active and integration.sync_enabled:
            self._schedule_job(integration)

    async def _run_sync(self, integration_id: str, user_id: str) -> None:
        """Execute a sync for a single integration. Called by APScheduler."""
        import uuid as _uuid
        from app.services.ingestion.pipeline import IngestionPipeline

        session_factory = get_session_factory()
        async with session_factory() as db:
            # Reload integration from DB
            result = await db.execute(
                select(Integration).where(Integration.id == _uuid.UUID(integration_id))
            )
            integration = result.scalar_one_or_none()
            if not integration or not integration.is_active or not integration.sync_enabled:
                logger.info("Skipping sync for %s — inactive or disabled", integration_id)
                return

            platform = integration.platform.value
            logger.info("Starting server-side sync: platform=%s user=%s", platform, user_id)

            try:
                # Import connector and run sync
                from app.api.routers.ingestion import _CONNECTORS
                from app.services import integration_service

                if platform not in _CONNECTORS:
                    integration.last_sync_status = "error"
                    integration.last_sync_error = "Unknown platform: {0}".format(platform)
                    await db.commit()
                    return

                from app.services.ingestion.embedder import Embedder

                token = integration_service.get_decrypted_token(integration)
                connector = _CONNECTORS[platform]()  # type: ignore[abstract]
                items = await connector.fetch_items(
                    access_token=token,
                    since=integration.last_sync_at,
                )

                pipeline = IngestionPipeline(embedder=Embedder())
                result = await pipeline.ingest_batch(
                    db=db,
                    user_id=_uuid.UUID(user_id),
                    items=[item.to_dict() for item in items],
                    source=platform,
                )

                integration.last_sync_at = datetime.now(timezone.utc)
                integration.last_sync_status = "success"
                integration.last_sync_error = None
                await db.commit()

                logger.info(
                    "Server-side sync complete: platform=%s created=%d updated=%d",
                    platform, result.documents_created, result.documents_updated,
                )

            except Exception as e:
                integration.last_sync_status = "error"
                integration.last_sync_error = str(e)[:500]
                integration.last_sync_at = datetime.now(timezone.utc)
                await db.commit()
                logger.exception("Server-side sync failed: platform=%s", platform)

    def get_job_info(self) -> List[Dict]:
        """Get info about all scheduled jobs."""
        if not self._scheduler or not HAS_APSCHEDULER:
            return []

        jobs = self._scheduler.get_jobs()  # type: ignore[attr-defined]
        result = []
        for job in jobs:
            next_run = job.next_run_time
            result.append({
                "job_id": job.id,
                "next_run": next_run.isoformat() if next_run else None,
            })
        return result
