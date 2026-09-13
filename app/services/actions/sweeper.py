"""Periodic sweep for ProposedAction rows stuck in EXECUTING.

app/api/routers/interactions.py's approve_action commits `EXECUTING`
before calling executor.execute() — a crash or a killed process between
those two points used to leave the row in EXECUTING forever, with no way
to know whether the real-world side effect (e.g. a Notion write)
actually happened, and no way for a human to retry (the row never
reaches a terminal state). This module doesn't resolve that ambiguity —
it can't, the outcome is genuinely unknown — it just ages the row out to
FAILED after a grace period so a human can see it happened and decide
whether to re-propose, instead of the row silently sitting stuck.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.proposed_action import ActionStatus, ProposedAction
from app.services.actions import store as actions_store

logger = logging.getLogger(__name__)

# APScheduler is optional — import safely, same convention as
# app/services/sync/scheduler.py and app/services/agent/knowledge/scheduler.py.
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.info("APScheduler not installed — action sweeper disabled")

# How long a row may sit in EXECUTING before it's considered stuck —
# generous relative to any real executor today (notion_publish makes one
# HTTP call), because this is meant to catch a crashed/killed process,
# not to race a slow-but-alive one.
STUCK_EXECUTING_GRACE = timedelta(minutes=10)
SWEEP_INTERVAL_MINUTES = 5


class ActionSweeper:
    """Runs a periodic job marking long-stuck EXECUTING rows as FAILED.
    Pure DB housekeeping — no external API/LLM calls, so unlike the sync
    and knowledge schedulers this has no meaningful cost and needs no
    opt-in flag; it's always started when APScheduler is available.
    """

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
        if self._running:
            return
        if not self._scheduler or not HAS_APSCHEDULER:
            logger.warning("Cannot start action sweeper — APScheduler not available")
            return
        self._scheduler.add_job(  # type: ignore[attr-defined]
            self._sweep,
            IntervalTrigger(minutes=SWEEP_INTERVAL_MINUTES),
            id="action_sweeper",
            replace_existing=True,
        )
        self._scheduler.start()  # type: ignore[attr-defined]
        self._running = True
        logger.info(
            "Action sweeper started (interval=%sm, grace=%s)",
            SWEEP_INTERVAL_MINUTES, STUCK_EXECUTING_GRACE,
        )

    async def shutdown(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            self._running = False
            logger.info("Action sweeper stopped")

    async def _sweep(self) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db:
            cutoff = datetime.now(timezone.utc) - STUCK_EXECUTING_GRACE
            result = await db.execute(
                select(ProposedAction).where(
                    ProposedAction.status == ActionStatus.EXECUTING,
                    ProposedAction.updated_at < cutoff,
                )
            )
            stuck = result.scalars().all()
            for action in stuck:
                logger.warning(
                    "Action sweeper: marking stuck EXECUTING action_id=%s (user=%s) as FAILED",
                    action.id, action.user_id,
                )
                await actions_store.mark_failed(
                    db, action.id,
                    "Execution timed out or the process crashed mid-execution — "
                    "the real-world outcome is unknown. Re-propose if it still needs to happen.",
                )
                await actions_store.write_audit(
                    db, action.id, event="failed", actor="system",
                    detail={"reason": "stuck_in_executing_swept"},
                )
            if stuck:
                await db.commit()
