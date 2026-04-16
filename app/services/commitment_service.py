import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.api.schemas.commitment import CommitmentCreate, CommitmentUpdate


async def create_commitment(db: AsyncSession, data: CommitmentCreate) -> Commitment:
    commitment = Commitment(
        id=uuid.uuid4(),
        user_id=data.user_id,
        document_id=data.document_id,
        commitment_text=data.commitment_text,
        due_date=data.due_date,
        priority=data.priority,
    )
    db.add(commitment)
    await db.flush()
    await db.refresh(commitment)
    return commitment


async def get_commitment(db: AsyncSession, commitment_id: uuid.UUID) -> Optional[Commitment]:
    result = await db.execute(
        select(Commitment).where(Commitment.id == commitment_id)
    )
    return result.scalar_one_or_none()


async def list_commitments(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: Optional[CommitmentStatus] = None,
    due_before: Optional[datetime] = None,
) -> List[Commitment]:
    query = select(Commitment).where(Commitment.user_id == user_id)
    if status is not None:
        query = query.where(Commitment.status == status)
    if due_before is not None:
        query = query.where(Commitment.due_date <= due_before)
    query = query.order_by(
        Commitment.priority.asc(),
        Commitment.due_date.asc().nullslast(),
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_commitment(
    db: AsyncSession, commitment: Commitment, data: CommitmentUpdate
) -> Commitment:
    if data.status is not None:
        # Validate status transition: only pending -> completed/cancelled
        if commitment.status != CommitmentStatus.PENDING:
            raise ValueError(
                f"Cannot transition from '{commitment.status.value}' — "
                f"only 'pending' commitments can be updated"
            )
        commitment.status = data.status
    if data.due_date is not None:
        commitment.due_date = data.due_date
    if data.priority is not None:
        commitment.priority = data.priority
    await db.flush()
    await db.refresh(commitment)
    return commitment


async def delete_commitment(db: AsyncSession, commitment: Commitment) -> None:
    await db.delete(commitment)
    await db.flush()
