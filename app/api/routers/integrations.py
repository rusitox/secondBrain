import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.integration import IntegrationCreate, IntegrationRead, IntegrationUpdate
from app.models.integration import Platform
from app.services import integration_service, user_service

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post("/", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
async def create_integration(
    data: IntegrationCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRead:
    if data.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create integrations for another user",
        )
    user = await user_service.get_user(db, data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    integration = await integration_service.create_integration(db, data)
    return IntegrationRead.model_validate(integration)


@router.get("/", response_model=List[IntegrationRead])
async def list_integrations(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    platform: Optional[Platform] = Query(None),
) -> List[IntegrationRead]:
    integrations = await integration_service.list_integrations(
        db, current_user_id, platform=platform
    )
    return [IntegrationRead.model_validate(i) for i in integrations]


@router.get("/{integration_id}", response_model=IntegrationRead)
async def get_integration(
    integration_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRead:
    integration = await integration_service.get_integration(db, integration_id)
    if not integration or integration.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    return IntegrationRead.model_validate(integration)


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def update_integration(
    integration_id: uuid.UUID,
    data: IntegrationUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationRead:
    integration = await integration_service.get_integration(db, integration_id)
    if not integration or integration.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    updated = await integration_service.update_integration(db, integration, data)
    return IntegrationRead.model_validate(updated)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    integration = await integration_service.get_integration(db, integration_id)
    if not integration or integration.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    await integration_service.delete_integration(db, integration)
