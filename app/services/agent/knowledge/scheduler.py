"""Server-side scheduler for the multi-agent knowledge system.

Mirrors app/services/sync/scheduler.py's pattern (APScheduler, optional
import, one job per user), but for a different concern: SyncScheduler pulls
raw data in (connector -> documents table); this schedules the periodic
"knowledge cycle" that turns already-ingested documents into the shared
entity/claim graph.

Explicitly opt-in (`settings.enable_knowledge_agents`) — unlike SyncScheduler,
this is NOT auto-enabled in production, since every cycle makes real LLM
calls (Strands agent invocations) on top of whatever ingestion already costs.

Backfill: knowledge_processed_documents starts empty, so the first cycle for
any user finds their *entire* pre-existing document history as "unprocessed"
— there is no separate migration step. Draining a large backlog happens
gradually, one `knowledge_agent_batch_size` slice per source per cycle, at
`knowledge_agent_interval_minutes` cadence, rather than in one large burst —
this bounds cost/latency per cycle at the expense of a slower initial
backfill for accounts with a lot of history.
"""
import logging
import uuid as _uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.integration import Integration

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.info("APScheduler not installed — knowledge agent scheduling disabled")


class KnowledgeAgentScheduler:
    """Runs one periodic "knowledge cycle" job per user with active integrations."""

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
            logger.warning("Cannot start knowledge agent scheduler — APScheduler not available")
            return

        self._scheduler.start()  # type: ignore[attr-defined]
        self._running = True
        logger.info("Knowledge agent scheduler started")

        await self._load_jobs()

    async def shutdown(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            self._running = False
            logger.info("Knowledge agent scheduler stopped")

    async def _load_jobs(self) -> None:
        """One job per distinct user_id with at least one active integration.

        Reuses the same "has an active integration" signal SyncScheduler
        already uses to decide who has data worth extracting — a user with
        no active integration has nothing in `documents` for these agents
        to read regardless of the I+D/MCP agent's own independent config.
        """
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Integration.user_id)
                .where(Integration.is_active == True)  # noqa: E712
                .distinct()
            )
            user_ids = [row[0] for row in result.all()]

            for user_id in user_ids:
                self._schedule_job(user_id)

            logger.info("Loaded %d knowledge agent jobs", len(user_ids))

    def _schedule_job(self, user_id: _uuid.UUID) -> None:
        if not self._scheduler or not HAS_APSCHEDULER:
            return

        from app.core.config import get_settings
        settings = get_settings()

        job_id = f"knowledge_cycle_{user_id}"
        interval = max(settings.knowledge_agent_interval_minutes, 5)  # minimum 5 minutes

        trigger = IntervalTrigger(minutes=interval)  # type: ignore[possibly-undefined]
        self._scheduler.add_job(  # type: ignore[attr-defined]
            self._run_cycle,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs={"user_id": str(user_id)},
        )
        logger.info("Scheduled knowledge cycle job %s: interval=%dm", job_id, interval)

    async def _run_cycle(self, user_id: str) -> None:
        """One knowledge cycle for one user: every Document-backed domain
        agent, then the I+D/MCP agent if configured, then reconciliation.

        Each step gets its own fresh AsyncSession and commits independently
        — one source failing (or reconciliation failing) must not roll back
        or block the others, same rationale as SyncScheduler._run_sync
        isolating failures per integration.
        """
        from app.core.config import get_settings
        from app.services.agent.knowledge.domain_agent import REGISTERED_SOURCES, run_domain_agent
        from app.services.agent.knowledge.rd_agent import run_rd_domain_agent
        from app.services.agent.knowledge.reconciliation import run_reconciliation
        from app.services.ingestion.embedder import Embedder

        settings = get_settings()
        embedder = Embedder(api_key=settings.openai_api_key) if settings.openai_api_key else None
        uid = _uuid.UUID(user_id)
        session_factory = get_session_factory()

        def _make_domain_agent_call(
            source: str,
        ) -> Callable[[AsyncSession], Awaitable[Dict[str, Any]]]:
            async def _call(db: AsyncSession) -> Dict[str, Any]:
                return await run_domain_agent(
                    source, db, uid, batch_size=settings.knowledge_agent_batch_size, embedder=embedder,
                )
            return _call

        document_backed_sources = [s for s in REGISTERED_SOURCES if s != "rd"]
        for source in document_backed_sources:
            await self._run_step(
                session_factory, "domain_agent[{0}]".format(source), user_id,
                _make_domain_agent_call(source),
            )

        if settings.id_brain_mcp_url:
            await self._run_step(
                session_factory, "rd_agent", user_id,
                lambda db: run_rd_domain_agent(db, uid, embedder=embedder),
            )

        await self._run_step(
            session_factory, "reconciliation", user_id,
            lambda db: run_reconciliation(db, uid),
        )

    @staticmethod
    async def _run_step(
        session_factory: Callable[[], AsyncSession],
        step_name: str,
        user_id: str,
        call: Callable[[AsyncSession], Awaitable[Dict[str, Any]]],
    ) -> None:
        async with session_factory() as db:  # type: AsyncSession
            try:
                result = await call(db)
                await db.commit()
                logger.info("Knowledge cycle step=%s user=%s result=%s", step_name, user_id, result)
            except Exception:
                await db.rollback()
                logger.exception("Knowledge cycle step=%s failed for user=%s", step_name, user_id)

    def get_job_info(self) -> List[Dict]:
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
