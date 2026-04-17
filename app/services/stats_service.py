"""Service layer for user statistics."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.models.document import Document
from app.models.integration import Integration


async def get_user_stats(db: AsyncSession, user_id: uuid.UUID) -> Dict[str, Any]:
    """Get aggregated statistics for a user."""
    # Count documents
    doc_result = await db.execute(
        select(func.count(Document.id)).where(Document.user_id == user_id)
    )
    documents_total = doc_result.scalar() or 0

    # Count pending commitments
    pending_result = await db.execute(
        select(func.count(Commitment.id)).where(
            Commitment.user_id == user_id,
            Commitment.status == CommitmentStatus.PENDING,
        )
    )
    commitments_pending = pending_result.scalar() or 0

    # Count overdue commitments
    now = datetime.now(timezone.utc)
    overdue_result = await db.execute(
        select(func.count(Commitment.id)).where(
            Commitment.user_id == user_id,
            Commitment.status == CommitmentStatus.PENDING,
            Commitment.due_date.isnot(None),
            Commitment.due_date <= now,
        )
    )
    commitments_overdue = overdue_result.scalar() or 0

    # Count integrations
    active_result = await db.execute(
        select(func.count(Integration.id)).where(
            Integration.user_id == user_id,
            Integration.is_active == True,  # noqa: E712
        )
    )
    integrations_active = active_result.scalar() or 0

    total_result = await db.execute(
        select(func.count(Integration.id)).where(
            Integration.user_id == user_id,
        )
    )
    integrations_total = total_result.scalar() or 0

    # Last sync time
    sync_result = await db.execute(
        select(func.max(Integration.last_sync_at)).where(
            Integration.user_id == user_id,
        )
    )
    last_sync: Optional[datetime] = sync_result.scalar()

    return {
        "documents_total": documents_total,
        "commitments_pending": commitments_pending,
        "commitments_overdue": commitments_overdue,
        "integrations_active": integrations_active,
        "integrations_total": integrations_total,
        "last_sync": last_sync,
    }
