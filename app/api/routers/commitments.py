import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.commitment import CommitmentCreate, CommitmentRead, CommitmentUpdate
from app.models.commitment import CommitmentStatus
from app.services import commitment_service, user_service

router = APIRouter(prefix="/commitments", tags=["commitments"])


@router.post("/", response_model=CommitmentRead, status_code=status.HTTP_201_CREATED)
async def create_commitment(
    data: CommitmentCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CommitmentRead:
    # Enforce row-level isolation
    if data.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create commitments for another user",
        )
    # Verify user exists
    user = await user_service.get_user(db, data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    commitment = await commitment_service.create_commitment(db, data)
    return CommitmentRead.model_validate(commitment)


@router.get("/", response_model=List[CommitmentRead])
async def list_commitments(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    commitment_status: Optional[CommitmentStatus] = Query(None, alias="status"),
    due_before: Optional[datetime] = Query(None),
) -> List[CommitmentRead]:
    commitments = await commitment_service.list_commitments(
        db, current_user_id, status=commitment_status, due_before=due_before
    )
    return [CommitmentRead.model_validate(c) for c in commitments]


@router.get("/{commitment_id}", response_model=CommitmentRead)
async def get_commitment(
    commitment_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CommitmentRead:
    commitment = await commitment_service.get_commitment(db, commitment_id)
    if not commitment or commitment.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commitment not found",
        )
    return CommitmentRead.model_validate(commitment)


@router.patch("/{commitment_id}", response_model=CommitmentRead)
async def update_commitment(
    commitment_id: uuid.UUID,
    data: CommitmentUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CommitmentRead:
    commitment = await commitment_service.get_commitment(db, commitment_id)
    if not commitment or commitment.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commitment not found",
        )
    try:
        updated = await commitment_service.update_commitment(db, commitment, data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    return CommitmentRead.model_validate(updated)


@router.delete("/{commitment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_commitment(
    commitment_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    commitment = await commitment_service.get_commitment(db, commitment_id)
    if not commitment or commitment.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commitment not found",
        )
    await commitment_service.delete_commitment(db, commitment)
