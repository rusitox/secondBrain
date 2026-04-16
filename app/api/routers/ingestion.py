"""Ingestion API endpoints.

POST /ingest/raw — ingest raw text (for testing / manual ingestion)
POST /ingest/sync/{platform} — trigger sync for a platform connector
GET /ingest/status/{integration_id} — check sync status
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.ingestion import IngestRawRequest, IngestResult, SyncStatusResponse
from app.core.config import get_settings
from app.services import integration_service
from app.services.connectors.msgraph import MSGraphConnector
from app.services.connectors.slack import SlackConnector
from app.services.connectors.fathom import FathomConnector
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

# Connector registry
_CONNECTORS = {
    "outlook": MSGraphConnector,
    "slack": SlackConnector,
    "fathom": FathomConnector,
}

# Module-level pipeline singleton (lazy-initialized)
_pipeline: Optional[IngestionPipeline] = None


def _get_pipeline() -> IngestionPipeline:
    global _pipeline
    if _pipeline is None:
        settings = get_settings()
        embedder = Embedder(api_key=settings.openai_api_key)
        _pipeline = IngestionPipeline(embedder=embedder)
    return _pipeline


@router.post("/raw", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_raw(
    data: IngestRawRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """Ingest raw text content. Useful for testing and manual ingestion."""
    if data.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot ingest for another user",
        )
    pipeline = _get_pipeline()
    result = await pipeline.ingest_raw(
        db=db,
        user_id=data.user_id,
        content=data.content,
        source=data.source,
        source_id=data.source_id,
        metadata=data.metadata_,
    )
    return IngestResult(**result.to_dict())


@router.post("/sync/{platform}", response_model=IngestResult)
async def sync_platform(
    platform: str,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    """Trigger a sync for a specific platform connector."""
    if platform not in _CONNECTORS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform: {platform}. Supported: {list(_CONNECTORS.keys())}",
        )

    # Find active integration for this user + platform
    integrations = await integration_service.list_integrations(
        db, current_user_id, platform=None,
    )
    integration = None
    for integ in integrations:
        if integ.platform.value == platform and integ.is_active:
            integration = integ
            break

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {platform} integration found",
        )

    # Decrypt token and fetch items
    token = integration_service.get_decrypted_token(integration)
    connector = _CONNECTORS[platform]()
    try:
        items = await connector.fetch_items(
            access_token=token,
            since=integration.last_sync_at,
        )
    except httpx.HTTPStatusError as e:
        logger.error("Connector %s returned HTTP %s: %s", platform, e.response.status_code, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Platform {platform} returned error: {e.response.status_code}",
        )
    except (httpx.HTTPError, RuntimeError) as e:
        logger.error("Connector %s failed: %s", platform, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch from {platform}: {str(e)}",
        )

    # Ingest fetched items
    pipeline = _get_pipeline()
    result = await pipeline.ingest_batch(
        db=db,
        user_id=current_user_id,
        items=[item.to_dict() for item in items],
        source=platform,
    )

    # Update last_sync_at
    integration.last_sync_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "Sync complete for %s (user=%s): %d created, %d updated",
        platform, current_user_id, result.documents_created, result.documents_updated,
    )
    return IngestResult(**result.to_dict())


@router.get("/status/{integration_id}", response_model=SyncStatusResponse)
async def get_sync_status(
    integration_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    """Check the sync status of an integration."""
    integration = await integration_service.get_integration(db, integration_id)
    if not integration or integration.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )
    return SyncStatusResponse(
        integration_id=integration.id,
        platform=integration.platform.value,
        is_active=integration.is_active,
        last_sync_at=integration.last_sync_at.isoformat() if integration.last_sync_at else None,
    )
