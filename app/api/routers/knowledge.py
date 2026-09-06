"""Observability for the multi-agent knowledge system (specs/plan-multi-agent-knowledge.md, Phase 7).

Makes "the knowledge base gets more solid over time" a checkable claim
instead of an aspiration: entities by confidence bucket, claims by source,
open pending questions, and recently merged (same_as) entities.
"""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.knowledge import KnowledgeStatsResponse
from app.services.agent.knowledge import store

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/status", response_model=KnowledgeStatsResponse)
async def get_knowledge_status(
    request: Request,
    merged_window_hours: int = Query(default=24, ge=1, le=24 * 30),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Snapshot of the shared knowledge base's current solidity for this user."""
    stats = await store.get_knowledge_stats(db, current_user_id, merged_window_hours=merged_window_hours)

    scheduler = getattr(request.app.state, "knowledge_scheduler", None)
    scheduler_active = scheduler is not None and scheduler.is_running
    next_run = None
    if scheduler:
        job_id = f"knowledge_cycle_{current_user_id}"
        next_run = next(
            (job["next_run"] for job in scheduler.get_job_info() if job["job_id"] == job_id), None,
        )

    return {**stats, "scheduler_active": scheduler_active, "next_scheduled_run": next_run}
