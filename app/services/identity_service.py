"""Service layer for user identity (persona, tone, heuristics)."""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.identity import IdentityCreate, IdentityUpdate
from app.models.identity import Identity


async def create_identity(
    db: AsyncSession, user_id: uuid.UUID, data: IdentityCreate
) -> Identity:
    """Create an identity for a user."""
    identity = Identity(
        id=uuid.uuid4(),
        user_id=user_id,
        persona_description=data.persona_description,
        tone_guidelines=data.tone_guidelines,
        heuristics=data.heuristics,
    )
    db.add(identity)
    await db.flush()
    await db.refresh(identity)
    return identity


async def get_identity(
    db: AsyncSession, user_id: uuid.UUID
) -> Optional[Identity]:
    """Get the identity for a user (one per user)."""
    result = await db.execute(
        select(Identity).where(Identity.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_identity(
    db: AsyncSession, identity: Identity, data: IdentityUpdate
) -> Identity:
    """Update an existing identity."""
    if data.persona_description is not None:
        identity.persona_description = data.persona_description
    if data.tone_guidelines is not None:
        identity.tone_guidelines = data.tone_guidelines
    if data.heuristics is not None:
        identity.heuristics = data.heuristics
    await db.flush()
    await db.refresh(identity)
    return identity
