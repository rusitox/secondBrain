"""Persistence for ProposedAction's approve/execute lifecycle and its
append-only audit trail. See app/models/proposed_action.py and
app/api/routers/interactions.py's approve_action endpoint — the only
caller of the write side of this module; propose_action (strands_tools.py)
only ever creates a row directly, never transitions one via this module.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_audit import ActionAuditLog
from app.models.proposed_action import ActionStatus, ProposedAction


async def claim_action_for_approval(
    db: AsyncSession, user_id: uuid.UUID, action_id: uuid.UUID,
) -> Optional[ProposedAction]:
    """Atomically transition a PROPOSED action to APPROVED.

    Returns None if it wasn't proposed, didn't belong to this user, or has
    expired — the caller must treat that as a conflict, never retry.
    ``synchronize_session="fetch"``: see
    interactions_store.claim_interaction_for_answer's docstring — the
    default "evaluate" strategy crashes comparing an aware ``now`` against
    a naive ``expires_at`` SQLite (and some driver configs) return for an
    already-identity-mapped row.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ProposedAction)
        .where(
            ProposedAction.id == action_id,
            ProposedAction.user_id == user_id,
            ProposedAction.status == ActionStatus.PROPOSED,
            ProposedAction.expires_at > now,
        )
        .values(status=ActionStatus.APPROVED, approved_at=now)
        .returning(ProposedAction),
        execution_options={"synchronize_session": "fetch"},
    )
    return result.scalar_one_or_none()


async def reject_action(
    db: AsyncSession, user_id: uuid.UUID, action_id: uuid.UUID,
) -> Optional[ProposedAction]:
    """Atomically transition a PROPOSED action to REJECTED — the human
    declining it. Returns None if it wasn't proposed or didn't belong to
    this user. No payload_sha256 check like approval's: rejecting doesn't
    need to agree on exact bytes the way committing an action does.
    """
    result = await db.execute(
        update(ProposedAction)
        .where(
            ProposedAction.id == action_id,
            ProposedAction.user_id == user_id,
            ProposedAction.status == ActionStatus.PROPOSED,
        )
        .values(status=ActionStatus.REJECTED)
        .returning(ProposedAction),
        execution_options={"synchronize_session": "fetch"},
    )
    return result.scalar_one_or_none()


async def mark_executing(db: AsyncSession, action_id: uuid.UUID) -> None:
    await db.execute(
        update(ProposedAction).where(ProposedAction.id == action_id).values(status=ActionStatus.EXECUTING),
        execution_options={"synchronize_session": "fetch"},
    )


async def mark_executed(db: AsyncSession, action_id: uuid.UUID, result: Dict[str, Any]) -> None:
    await db.execute(
        update(ProposedAction).where(ProposedAction.id == action_id).values(
            status=ActionStatus.EXECUTED, executed_at=datetime.now(timezone.utc), result=result,
        ),
        execution_options={"synchronize_session": "fetch"},
    )


async def mark_failed(db: AsyncSession, action_id: uuid.UUID, error: str) -> None:
    await db.execute(
        update(ProposedAction).where(ProposedAction.id == action_id).values(
            status=ActionStatus.FAILED, executed_at=datetime.now(timezone.utc), error=error,
        ),
        execution_options={"synchronize_session": "fetch"},
    )


async def write_audit(
    db: AsyncSession,
    action_id: uuid.UUID,
    event: str,
    actor: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(ActionAuditLog(action_id=action_id, event=event, actor=actor, detail=detail))
    await db.flush()
