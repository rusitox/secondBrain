"""Observability for the multi-agent knowledge system (specs/plan-multi-agent-knowledge.md, Phase 7).

Makes "the knowledge base gets more solid over time" a checkable claim
instead of an aspiration: entities by confidence bucket, claims by source,
open pending questions, and recently merged (same_as) entities.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.knowledge import KnowledgeStatsResponse
from app.services.agent.knowledge import store

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/status", response_model=KnowledgeStatsResponse)
async def get_knowledge_status(
    merged_window_hours: int = Query(default=24, ge=1, le=24 * 30),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Snapshot of the shared knowledge base's current solidity for this user."""
    return await store.get_knowledge_stats(db, current_user_id, merged_window_hours=merged_window_hours)
