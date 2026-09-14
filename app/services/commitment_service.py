import uuid
from datetime import datetime
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.models.user import User
from app.api.schemas.commitment import CommitmentCreate, CommitmentUpdate

# Free-text owner values the commitment detector emits when it could not
# identify a specific person — never treat these as "the account holder".
_AMBIGUOUS_OWNERS: Set[str] = {"", "unknown", "speaker"}


def is_owned_by_user(owner: Optional[str], user: Optional[User]) -> bool:
    """Whether a commitment's free-text `owner` clearly refers to `user`.

    Commitment.owner is unstructured text an LLM pulled out of meeting/
    message content — it can just as easily name someone else ("Daniel",
    "Santiago") as the account holder. Surfacing someone else's commitment
    as the user's own is misleading, so this fails closed: an owner that
    doesn't clearly match is treated as NOT the user's, not as "probably
    mine". Matches against full name, first name, email, and the email's
    local part, case-insensitively.
    """
    if not owner or user is None:
        return False
    owner_norm = owner.strip().lower()
    if not owner_norm or owner_norm in _AMBIGUOUS_OWNERS:
        return False

    candidates: Set[str] = set()
    full_name = (user.full_name or "").strip().lower()
    if full_name:
        candidates.add(full_name)
        candidates.add(full_name.split()[0])
    email = (user.email or "").strip().lower()
    if email:
        candidates.add(email)
        candidates.add(email.split("@")[0])

    return owner_norm in candidates


async def create_commitment(db: AsyncSession, data: CommitmentCreate) -> Commitment:
    commitment = Commitment(
        id=uuid.uuid4(),
        user_id=data.user_id,
        document_id=data.document_id,
        commitment_text=data.commitment_text,
        owner=data.owner,
        delivered_to=data.delivered_to,
        due_date=data.due_date,
        priority=data.priority,
    )
    db.add(commitment)
    await db.flush()
    await db.refresh(commitment)
    return commitment


async def get_commitment(db: AsyncSession, commitment_id: uuid.UUID) -> Optional[Commitment]:
    result = await db.execute(
        select(Commitment)
        .where(Commitment.id == commitment_id)
        .options(selectinload(Commitment.document))
    )
    return result.scalar_one_or_none()


async def list_commitments(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: Optional[CommitmentStatus] = None,
    due_before: Optional[datetime] = None,
) -> List[Commitment]:
    query = (
        select(Commitment)
        .where(Commitment.user_id == user_id)
        .options(selectinload(Commitment.document))
    )
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
    if data.owner is not None:
        commitment.owner = data.owner
    if data.commitment_text is not None:
        commitment.commitment_text = data.commitment_text
    await db.flush()
    await db.refresh(commitment)
    return commitment


async def delete_commitment(db: AsyncSession, commitment: Commitment) -> None:
    await db.delete(commitment)
    await db.flush()
