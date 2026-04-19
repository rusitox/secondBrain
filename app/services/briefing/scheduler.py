"""Briefing scheduler using APScheduler.

Provides cron-based scheduling for daily briefing generation.
For MVP: in-process scheduler (single-user). Production: Celery + Redis.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# APScheduler is optional for MVP — import safely
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.jobstores.base import JobLookupError
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    JobLookupError = LookupError  # type: ignore[misc,assignment]
    logger.info("APScheduler not installed — briefing scheduling disabled")


class BriefingScheduler:
    """Manages scheduled briefing generation jobs."""

    def __init__(self) -> None:
        self._scheduler: Optional[object] = None
        if HAS_APSCHEDULER:
            self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler and HAS_APSCHEDULER:
            self._scheduler.start()  # type: ignore[attr-defined]
            logger.info("Briefing scheduler started")

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self._scheduler and HAS_APSCHEDULER:
            self._scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            logger.info("Briefing scheduler stopped")

    def schedule_briefing(
        self,
        job_id: str,
        func: object,
        hour: int = 7,
        minute: int = 0,
        timezone_str: str = "UTC",
    ) -> bool:
        """Schedule a daily briefing job.

        Args:
            job_id: Unique identifier for the job.
            func: Async callable to execute.
            hour: Hour to run (0-23).
            minute: Minute to run (0-59).
            timezone_str: Timezone for the schedule.

        Returns:
            True if scheduled successfully, False if APScheduler unavailable.
        """
        if not self._scheduler or not HAS_APSCHEDULER:
            logger.warning("Cannot schedule briefing — APScheduler not available")
            return False

        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone_str)  # type: ignore[possibly-undefined]
        self._scheduler.add_job(  # type: ignore[attr-defined]
            func, trigger=trigger, id=job_id, replace_existing=True,
        )
        logger.info(
            "Scheduled briefing job %s at %02d:%02d %s",
            job_id, hour, minute, timezone_str,
        )
        return True

    def remove_briefing(self, job_id: str) -> bool:
        """Remove a scheduled briefing job."""
        if not self._scheduler or not HAS_APSCHEDULER:
            return False
        try:
            self._scheduler.remove_job(job_id)  # type: ignore[attr-defined]
            logger.info("Removed briefing job %s", job_id)
            return True
        except (JobLookupError, KeyError):
            logger.warning("Job %s not found for removal", job_id)
            return False

    @property
    def is_available(self) -> bool:
        """Check if scheduling is available."""
        return HAS_APSCHEDULER
