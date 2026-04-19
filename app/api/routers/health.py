import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_start_time = time.monotonic()


class HealthResponse(BaseModel):
    status: str
    message: str


class DetailedHealthResponse(BaseModel):
    status: str
    environment: str
    version: str
    uptime_seconds: int
    database: str
    database_error: Optional[str] = None


@router.get("/", response_model=HealthResponse)
async def root() -> dict:
    return {"status": "online", "message": "Digital Twin Core is active and ready."}


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def health_detailed(db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    uptime = int(time.monotonic() - _start_time)

    db_status = "healthy"
    db_error = None
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "unhealthy"
        db_error = str(e) if not settings.is_production else "connection failed"
        logger.error("Health check: database unreachable: %s", e)

    overall = "healthy" if db_status == "healthy" else "degraded"

    return {
        "status": overall,
        "environment": settings.app_env,
        "version": "0.1.0",
        "uptime_seconds": uptime,
        "database": db_status,
        "database_error": db_error,
    }
