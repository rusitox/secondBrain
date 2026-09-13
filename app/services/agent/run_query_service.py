"""Read-only queries over AgentRun/AgentRunEvent — backs the backoffice's
runs/traces listing. specs/plan-knowledge-backoffice.md, Phase 4.

Not part of app.services.agent.tracing on purpose: tracing.py only ever
writes (and deliberately swallows its own failures, since it must never be
why an agent run fails); this module only reads, and lets real errors
propagate like every other read path in the API (e.g. app/services/agent/
knowledge/store.py) — a broken query here should surface as a 500, not be
silently absorbed the way a broken trace write is.
"""
import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, RunStatus, RunType
from app.models.agent_run_event import AgentRunEvent


async def count_runs(
    db: AsyncSession, user_id: uuid.UUID, agent_key: Optional[str] = None,
) -> int:
    stmt = select(func.count()).select_from(AgentRun).where(AgentRun.user_id == user_id)
    if agent_key is not None:
        stmt = stmt.where(AgentRun.agent_key == agent_key)
    return (await db.execute(stmt)).scalar_one()


async def list_runs(
    db: AsyncSession,
    user_id: uuid.UUID,
    agent_key: Optional[str] = None,
    status: Optional[RunStatus] = None,
    run_type: Optional[RunType] = None,
    top_level: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.user_id == user_id)
    if agent_key is not None:
        stmt = stmt.where(AgentRun.agent_key == agent_key)
    if status is not None:
        stmt = stmt.where(AgentRun.status == status)
    if run_type is not None:
        stmt = stmt.where(AgentRun.run_type == run_type)
    if top_level:
        stmt = stmt.where(AgentRun.parent_run_id.is_(None))
    stmt = stmt.order_by(AgentRun.started_at.desc()).offset(offset).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def get_run(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Optional[AgentRun]:
    """Scoped by user_id — a run_id belonging to another user must never resolve."""
    stmt = select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_run_events(db: AsyncSession, run_id: uuid.UUID) -> List[AgentRunEvent]:
    """Not itself scoped by user_id (AgentRunEvent carries no user_id column)
    — callers must get_run() first to prove ownership of run_id, the same
    "check the parent, then trust the child's FK" pattern store.list_claims
    uses for entity_id."""
    stmt = (
        select(AgentRunEvent)
        .where(AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.seq)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_sub_runs(db: AsyncSession, user_id: uuid.UUID, parent_run_id: uuid.UUID) -> List[AgentRun]:
    """Negotiation runs a parent run triggered (ask_peer_agents/negotiate_same_as)."""
    stmt = (
        select(AgentRun)
        .where(AgentRun.user_id == user_id, AgentRun.parent_run_id == parent_run_id)
        .order_by(AgentRun.started_at)
    )
    return list((await db.execute(stmt)).scalars().all())
