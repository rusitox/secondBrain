"""Bidirectional sync between local commitments and the Notion Commitments database.

Handles three cases:
  1. Local commitments without a notion_page_id → create in Notion
  2. Notion rows not linked to any local commitment → skip (user-created)
  3. Both exist → compare updated_at vs last_edited_time, last-write-wins
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.services.notion.publisher import NotionPublisher

logger = logging.getLogger(__name__)

# Notion API base for querying databases
NOTION_API_BASE = "https://api.notion.com/v1"


@dataclass
class SyncResult:
    """Result of a bidirectional sync operation."""

    created_in_notion: int = 0
    updated_in_notion: int = 0
    updated_locally: int = 0
    errors: List[str] = field(default_factory=list)


def _normalize_notion_id(page_id: str) -> str:
    """Normalize a Notion page ID to UUID format with dashes."""
    clean = page_id.replace("-", "")
    if len(clean) == 32:
        return "%s-%s-%s-%s-%s" % (
            clean[:8], clean[8:12], clean[12:16], clean[16:20], clean[20:],
        )
    return page_id


class NotionSync:
    """Bidirectional commitment sync between local DB and Notion."""

    def __init__(self, publisher: NotionPublisher) -> None:
        self._publisher = publisher

    async def sync_commitments(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> SyncResult:
        """Run a full bidirectional commitment sync.

        Args:
            db: Database session.
            user_id: The user whose commitments to sync.

        Returns:
            SyncResult with counts and any errors.
        """
        result = SyncResult()

        # 1. Get local commitments
        local_commitments = await self._get_local_commitments(db, user_id)

        # 2. Get Notion commitments
        notion_rows = await self._get_notion_commitments()

        # 3. Build lookup: normalized notion_page_id → notion row
        notion_by_id: Dict[str, Dict[str, Any]] = {}
        for row in notion_rows:
            notion_by_id[_normalize_notion_id(row["id"])] = row

        # 4. Process local commitments
        for commitment in local_commitments:
            normalized_id = (
                _normalize_notion_id(commitment.notion_page_id)
                if commitment.notion_page_id else None
            )
            if not normalized_id:
                # Case 1: New local → create in Notion
                await self._push_to_notion(commitment, result)
                await db.flush()
            elif normalized_id in notion_by_id:
                # Case 3: Both exist → compare timestamps
                notion_row = notion_by_id.pop(normalized_id)
                await self._resolve_conflict(
                    db, commitment, notion_row, result,
                )

        await db.flush()
        logger.info(
            "Sync complete: created=%d, updated_notion=%d, updated_local=%d, errors=%d",
            result.created_in_notion,
            result.updated_in_notion,
            result.updated_locally,
            len(result.errors),
        )
        return result

    async def _get_local_commitments(
        self, db: AsyncSession, user_id: uuid.UUID,
    ) -> List[Commitment]:
        """Fetch all non-cancelled commitments for user."""
        stmt = (
            select(Commitment)
            .where(Commitment.user_id == user_id)
            .where(Commitment.status != CommitmentStatus.CANCELLED)
        )
        rows = await db.execute(stmt)
        return list(rows.scalars().all())

    async def _get_notion_commitments(self) -> List[Dict[str, Any]]:
        """Query the Notion Commitments database for all rows."""
        db_id = self._publisher._config.commitments_db_id
        if not db_id:
            return []

        import httpx
        from urllib.parse import quote

        safe_id = quote(db_id, safe="")
        url = NOTION_API_BASE + "/databases/" + safe_id + "/query"
        headers = self._publisher._build_headers()

        rows: List[Dict[str, Any]] = []
        start_cursor = None
        max_pages = 50

        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(max_pages):
                body: Dict[str, Any] = {}
                if start_cursor:
                    body["start_cursor"] = start_cursor

                resp = await self._publisher._api_call(
                    client, headers, "POST", url, body,
                )
                for item in resp.get("results", []):
                    rows.append(item)

                if not resp.get("has_more", False):
                    break
                start_cursor = resp.get("next_cursor")

        return rows

    async def _push_to_notion(
        self, commitment: Commitment, result: SyncResult,
    ) -> None:
        """Create a local commitment in Notion and store the page ID."""
        try:
            page_id = await self._publisher.create_commitment_row({
                "commitment_text": commitment.commitment_text,
                "status": commitment.status.value,
                "priority": commitment.priority,
                "owner": commitment.owner,
                "due_date": (
                    commitment.due_date.strftime("%Y-%m-%d")
                    if commitment.due_date else None
                ),
                "source": "secondbrain",
                "created_at": commitment.created_at.isoformat()
                if commitment.created_at else None,
            })
            commitment.notion_page_id = _normalize_notion_id(page_id)
            result.created_in_notion += 1
        except (RuntimeError, httpx.HTTPError) as e:
            msg = "Failed to push commitment %s to Notion: %s" % (
                commitment.id, e,
            )
            logger.warning(msg)
            result.errors.append(msg)

    async def _resolve_conflict(
        self,
        db: AsyncSession,
        commitment: Commitment,
        notion_row: Dict[str, Any],
        result: SyncResult,
    ) -> None:
        """Resolve a conflict between local and Notion versions.

        Uses last-write-wins: compare commitment.updated_at with
        Notion's last_edited_time.
        """
        # Parse Notion's last_edited_time
        notion_edited_str = notion_row.get("last_edited_time", "")
        if not notion_edited_str:
            return

        try:
            cleaned = notion_edited_str.replace("Z", "+00:00")
            notion_edited = datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            return

        local_updated = commitment.updated_at
        if local_updated and local_updated.tzinfo is None:
            local_updated = local_updated.replace(tzinfo=timezone.utc)

        if notion_edited.tzinfo is None:
            notion_edited = notion_edited.replace(tzinfo=timezone.utc)

        # Extract Notion status
        notion_props = notion_row.get("properties", {})
        notion_status = self._extract_select(notion_props, "Status")
        notion_priority = self._extract_priority(notion_props, "Priority")

        if local_updated and local_updated > notion_edited:
            # Local is newer → push to Notion
            updates: Dict[str, Any] = {}
            if notion_status and notion_status.lower() != commitment.status.value:
                updates["status"] = commitment.status.value
            if notion_priority is not None and notion_priority != commitment.priority:
                updates["priority"] = commitment.priority
            if updates and commitment.notion_page_id:
                try:
                    await self._publisher.update_commitment_row(
                        commitment.notion_page_id, updates,
                    )
                    result.updated_in_notion += 1
                except (RuntimeError, httpx.HTTPError) as e:
                    result.errors.append(
                        "Failed to update Notion row %s: %s"
                        % (commitment.notion_page_id, e)
                    )
        else:
            # Notion is newer → pull to local
            changed = False
            if notion_status:
                mapped = notion_status.lower()
                if mapped in ("pending", "completed", "cancelled"):
                    new_status = CommitmentStatus(mapped)
                    if new_status != commitment.status:
                        commitment.status = new_status
                        changed = True
            if (
                notion_priority is not None
                and 1 <= notion_priority <= 5
                and notion_priority != commitment.priority
            ):
                commitment.priority = notion_priority
                changed = True

            if changed:
                result.updated_locally += 1

    @staticmethod
    def _extract_select(
        props: Dict[str, Any], field_name: str,
    ) -> Optional[str]:
        """Extract a select value from Notion properties."""
        prop = props.get(field_name, {})
        select_val = prop.get("select")
        if select_val and isinstance(select_val, dict):
            return select_val.get("name")
        return None

    @staticmethod
    def _extract_priority(
        props: Dict[str, Any], field_name: str,
    ) -> Optional[int]:
        """Extract priority number from 'P1'-style select value."""
        name = NotionSync._extract_select(props, field_name)
        if name and name.startswith("P") and len(name) == 2:
            try:
                return int(name[1])
            except ValueError:
                pass
        return None
