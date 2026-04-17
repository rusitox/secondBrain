"""Identity API endpoints.

POST /users/{user_id}/identity — create identity
GET /users/{user_id}/identity — get identity
PATCH /users/{user_id}/identity — update identity
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.identity import IdentityCreate, IdentityRead, IdentityUpdate
from app.services import identity_service

router = APIRouter(prefix="/users", tags=["identity"])


@router.post(
    "/{user_id}/identity",
    response_model=IdentityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_identity(
    user_id: uuid.UUID,
    data: IdentityCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IdentityRead:
    """Create an identity profile for the user."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create identity for another user",
        )
    existing = await identity_service.get_identity(db, user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity already exists — use PATCH to update",
        )
    identity = await identity_service.create_identity(db, user_id, data)
    return IdentityRead.model_validate(identity)


@router.get("/{user_id}/identity", response_model=IdentityRead)
async def get_identity(
    user_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IdentityRead:
    """Get the user's identity profile."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's identity",
        )
    identity = await identity_service.get_identity(db, user_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity not found — create one first",
        )
    return IdentityRead.model_validate(identity)


@router.patch("/{user_id}/identity", response_model=IdentityRead)
async def update_identity(
    user_id: uuid.UUID,
    data: IdentityUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IdentityRead:
    """Update the user's identity profile."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify another user's identity",
        )
    identity = await identity_service.get_identity(db, user_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity not found — create one first",
        )
    updated = await identity_service.update_identity(db, identity, data)
    return IdentityRead.model_validate(updated)
