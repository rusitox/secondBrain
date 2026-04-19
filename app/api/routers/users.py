import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.identity import UserStats
from app.api.schemas.user import (
    NotionConfigResponse,
    NotionConfigUpdate,
    OnboardingState,
    OnboardingUpdate,
    UserCreate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    UserRead,
    UserUpdate,
)
from app.services import user_service
from app.services import stats_service

router = APIRouter(prefix="/users", tags=["users"])


# --- /users/me endpoints (must be before /{user_id} to avoid route conflict) ---


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """Return preferences, onboarding state, and Notion config for current user."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPreferencesResponse(
        preferences=user.preferences,
        onboarding=OnboardingState(
            step=user.onboarding_step,
            completed=user.onboarding_completed,
        ),
        notion_config=user.notion_config,
    )


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_my_preferences(
    body: UserPreferencesUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """Merge new keys into existing preferences."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    merged = {**user.preferences, **body.preferences}
    user.preferences = merged
    await db.flush()
    return UserPreferencesResponse(
        preferences=user.preferences,
        onboarding=OnboardingState(
            step=user.onboarding_step,
            completed=user.onboarding_completed,
        ),
        notion_config=user.notion_config,
    )


@router.get("/me/onboarding", response_model=OnboardingState)
async def get_my_onboarding(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OnboardingState:
    """Return onboarding step and completion status."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return OnboardingState(step=user.onboarding_step, completed=user.onboarding_completed)


@router.patch("/me/onboarding", response_model=OnboardingState)
async def update_my_onboarding(
    body: OnboardingUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OnboardingState:
    """Update onboarding step and/or completion."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.step is not None:
        user.onboarding_step = body.step
    if body.completed is not None:
        user.onboarding_completed = body.completed
    await db.flush()
    return OnboardingState(step=user.onboarding_step, completed=user.onboarding_completed)


@router.get("/me/notion-config", response_model=NotionConfigResponse)
async def get_my_notion_config(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> NotionConfigResponse:
    """Return Notion workspace config."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return NotionConfigResponse(config=user.notion_config)


@router.put("/me/notion-config", response_model=NotionConfigResponse)
async def update_my_notion_config(
    body: NotionConfigUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> NotionConfigResponse:
    """Replace Notion config entirely."""
    user = await user_service.get_user(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.notion_config = body.config
    await db.flush()
    return NotionConfigResponse(config=user.notion_config)


# --- Standard CRUD ---


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    existing = await user_service.get_user_by_email(db, data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{data.email}' already exists",
        )
    user = await user_service.create_user(db, data)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's profile",
        )
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify another user's profile",
        )
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    updated = await user_service.update_user(db, user, data)
    return UserRead.model_validate(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete another user's profile",
        )
    user = await user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    await user_service.delete_user(db, user)


@router.get("/{user_id}/stats", response_model=UserStats)
async def get_user_stats(
    user_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserStats:
    """Get aggregated statistics for the user."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's stats",
        )
    stats = await stats_service.get_user_stats(db, user_id)
    return UserStats(**stats)
