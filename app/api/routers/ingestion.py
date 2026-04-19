"""Ingestion API endpoints.

POST /ingest/raw — ingest raw text (for testing / manual ingestion)
POST /ingest/sync/{platform} — trigger sync for a platform connector
GET /ingest/status/{integration_id} — check sync status
"""
import uuid
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.models.integration import Integration
from app.api.schemas.ingestion import (
    IngestRawRequest,
    IngestResult,
    NotionPublishBriefingRequest,
    NotionPublishDigestRequest,
    NotionPublishMeetingPrepRequest,
    NotionSyncCommitmentsRequest,
    SyncStatusResponse,
)
from app.core.config import get_settings
from app.services import integration_service
from app.services.connectors.msgraph import MSGraphConnector
from app.services.connectors.slack import SlackConnector
from app.services.connectors.fathom import FathomConnector
from app.services.connectors.teams import TeamsConnector
from app.services.connectors.notion import NotionConnector
from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.publisher import NotionPublisher
from app.services.notion.sync import NotionSync
from app.services.commitments.detector import CommitmentDetector
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.llm.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

# Connector registry
_CONNECTORS = {
    "outlook": MSGraphConnector,
    "slack": SlackConnector,
    "fathom": FathomConnector,
    "teams": TeamsConnector,
    "notion": NotionConnector,
}

@lru_cache(maxsize=1)
def _get_pipeline() -> IngestionPipeline:
    settings = get_settings()
    embedder = Embedder(api_key=settings.openai_api_key)
    # Wire in commitment detection if Claude API key is available
    commitment_detector: Optional[CommitmentDetector] = None
    if settings.claude_api_key:
        claude_client = ClaudeClient(api_key=settings.claude_api_key)
        commitment_detector = CommitmentDetector(claude_client)
    return IngestionPipeline(
        embedder=embedder,
        commitment_detector=commitment_detector,
    )


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


def _get_notion_token_and_config(
    notion_integ: Integration,
    workspace_config: dict,
) -> tuple:
    """Extract decrypted token and workspace config.

    The workspace config comes from the CLI request body since
    it is stored client-side, not on the Integration model.
    """
    token = integration_service.get_decrypted_token(notion_integ)
    ws_config = NotionWorkspaceConfig.from_dict(workspace_config)
    return token, ws_config


async def _find_notion_integration(
    db: AsyncSession, user_id: uuid.UUID,
) -> Integration:
    """Find the active Notion integration or raise 404."""
    integrations = await integration_service.list_integrations(
        db, user_id, platform=None,
    )
    for integ in integrations:
        if integ.platform.value == "notion" and integ.is_active:
            return integ
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No active Notion integration found",
    )


@router.post("/notion/sync-commitments")
async def sync_notion_commitments(
    body: NotionSyncCommitmentsRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bidirectional sync of commitments with Notion.

    The workspace_config is sent from the CLI since it stores
    the Notion workspace IDs (root page, database IDs) locally.
    """
    notion_integ = await _find_notion_integration(db, current_user_id)
    token, ws_config = _get_notion_token_and_config(notion_integ, body.workspace_config)

    if not ws_config.commitments_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notion workspace not set up — no commitments database",
        )

    publisher = NotionPublisher(token, ws_config)
    sync = NotionSync(publisher)

    try:
        result = await sync.sync_commitments(db, current_user_id)
    except (httpx.HTTPError, RuntimeError) as e:
        logger.error("Notion commitment sync failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notion sync failed: %s" % str(e),
        )

    return {
        "created_in_notion": result.created_in_notion,
        "updated_in_notion": result.updated_in_notion,
        "updated_locally": result.updated_locally,
        "errors": result.errors,
    }


@router.post("/notion/publish-briefing")
async def publish_briefing_to_notion(
    body: NotionPublishBriefingRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a briefing to Notion.

    Accepts the already-generated briefing text to avoid regenerating.
    The workspace_config is sent from the CLI.
    """
    notion_integ = await _find_notion_integration(db, current_user_id)
    token, ws_config = _get_notion_token_and_config(notion_integ, body.workspace_config)

    if not ws_config.briefings_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notion workspace not set up — no briefings database",
        )

    if not body.briefing_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No briefing text provided",
        )

    date_str = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    publisher = NotionPublisher(token, ws_config)
    try:
        url = await publisher.publish_briefing(body.briefing_text, date_str)
    except (httpx.HTTPError, RuntimeError) as e:
        logger.error("Failed to publish briefing to Notion: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to publish briefing to Notion",
        )

    return {"url": url, "date": date_str}


@router.post("/notion/publish-digest")
async def publish_digest_to_notion(
    body: NotionPublishDigestRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate and publish a weekly digest to Notion."""
    notion_integ = await _find_notion_integration(db, current_user_id)
    token, ws_config = _get_notion_token_and_config(notion_integ, body.workspace_config)

    if not ws_config.briefings_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notion workspace not set up — no briefings database",
        )

    # Generate digest
    from app.services.notion.digest import WeeklyDigestGenerator

    settings = get_settings()
    if not settings.claude_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claude API key not configured",
        )

    claude_client = ClaudeClient(api_key=settings.claude_api_key)
    generator = WeeklyDigestGenerator(claude_client)

    ws = None
    we = None
    if body.week_start:
        ws = datetime.fromisoformat(body.week_start).replace(tzinfo=timezone.utc)
    if body.week_end:
        we = datetime.fromisoformat(body.week_end).replace(tzinfo=timezone.utc)

    try:
        digest = await generator.generate(
            db=db, user_id=current_user_id, week_start=ws, week_end=we,
        )
    except Exception as e:
        logger.error("Failed to generate digest: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate weekly digest",
        )

    # Publish to Notion
    publisher = NotionPublisher(token, ws_config)
    try:
        url = await publisher.publish_weekly_digest(
            digest.digest_text, digest.week_start, digest.week_end,
        )
    except (httpx.HTTPError, RuntimeError) as e:
        logger.error("Failed to publish digest to Notion: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to publish digest to Notion",
        )

    return {
        "url": url,
        "week_start": digest.week_start,
        "week_end": digest.week_end,
        "stats": digest.to_dict(),
    }


@router.post("/notion/publish-meeting-prep")
async def publish_meeting_prep_to_notion(
    body: NotionPublishMeetingPrepRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish meeting prep to Notion."""
    notion_integ = await _find_notion_integration(db, current_user_id)
    token, ws_config = _get_notion_token_and_config(notion_integ, body.workspace_config)

    if not ws_config.meeting_prep_db_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notion workspace not set up — no meeting prep database",
        )

    date_str = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    publisher = NotionPublisher(token, ws_config)
    try:
        url = await publisher.publish_meeting_prep(body.title, body.prep_text, date_str)
    except (httpx.HTTPError, RuntimeError) as e:
        logger.error("Failed to publish meeting prep to Notion: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to publish meeting prep to Notion",
        )

    return {"url": url, "title": body.title, "date": date_str}
