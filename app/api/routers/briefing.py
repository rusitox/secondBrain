"""Briefing API endpoints.

GET /briefing/{user_id} — generate a daily briefing
POST /briefing/{user_id}/schedule — schedule daily briefing generation
"""
import uuid
import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from anthropic import APIError as AnthropicAPIError
from openai import APIError as OpenAIAPIError

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.briefing import BriefingResponse, ScheduleRequest, ScheduleResponse
from app.core.config import get_settings
from app.services.briefing.generator import BriefingGenerator
from app.services.briefing.scheduler import BriefingScheduler
from app.services.llm.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/briefing", tags=["briefing"])


@lru_cache(maxsize=1)
def _get_scheduler() -> BriefingScheduler:
    return BriefingScheduler()


@lru_cache(maxsize=1)
def _get_generator() -> BriefingGenerator:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is required for briefing generation")
    claude_client = ClaudeClient(api_key=settings.llm_api_key, model=settings.llm_model)
    return BriefingGenerator(claude_client=claude_client)


@router.get("/{user_id}", response_model=BriefingResponse)
async def get_briefing(
    user_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> BriefingResponse:
    """Generate a daily briefing for the user."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access briefing for another user",
        )

    generator = _get_generator()
    try:
        result = await generator.generate(db=db, user_id=user_id)
    except (RuntimeError, ValueError, AnthropicAPIError, OpenAIAPIError) as e:
        logger.error("Briefing generation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate briefing",
        )

    return BriefingResponse(**result.to_dict())


@router.post("/{user_id}/schedule", response_model=ScheduleResponse)
async def schedule_briefing(
    user_id: uuid.UUID,
    data: ScheduleRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ScheduleResponse:
    """Schedule a daily briefing for the user."""
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot schedule briefing for another user",
        )

    scheduler = _get_scheduler()
    if not scheduler.is_available:
        return ScheduleResponse(
            scheduled=False,
            message="Scheduling not available — APScheduler not installed",
        )

    job_id = f"briefing-{user_id}"

    async def _briefing_job() -> None:
        logger.warning(
            "Scheduled briefing fired for user %s — generation not yet wired (MVP placeholder)",
            user_id,
        )

    success = scheduler.schedule_briefing(
        job_id=job_id,
        func=_briefing_job,
        hour=data.hour,
        minute=data.minute,
        timezone_str=data.timezone,
    )

    if success:
        return ScheduleResponse(
            scheduled=True,
            message=f"Briefing scheduled daily at {data.hour:02d}:{data.minute:02d} {data.timezone}",
        )
    return ScheduleResponse(scheduled=False, message="Failed to schedule briefing")
