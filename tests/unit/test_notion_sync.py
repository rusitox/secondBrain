"""Unit tests for NotionSync bidirectional commitment sync."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.commitment import Commitment, CommitmentStatus
from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.sync import NotionSync, SyncResult


def _make_commitment(**overrides) -> Commitment:
    """Create a Commitment with test defaults."""
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        commitment_text="Test commitment",
        owner="Alice",
        status=CommitmentStatus.PENDING,
        priority=3,
        notion_page_id=None,
        due_date=None,
        created_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    c = MagicMock(spec=Commitment)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _make_notion_row(
    page_id: str,
    status: str = "Pending",
    priority: str = "P3",
    last_edited: str = "2026-04-15T00:00:00.000Z",
) -> dict:
    """Create a Notion database row dict."""
    return {
        "id": page_id,
        "last_edited_time": last_edited,
        "properties": {
            "Status": {"select": {"name": status}},
            "Priority": {"select": {"name": priority}},
        },
    }


def _make_publisher() -> MagicMock:
    """Create a mock NotionPublisher."""
    publisher = MagicMock()
    publisher._config = NotionWorkspaceConfig(
        enabled=True,
        commitments_db_id="commit-db-id",
    )
    publisher._build_headers = MagicMock(return_value={"Authorization": "Bearer test"})
    publisher._api_call = AsyncMock(return_value={"results": [], "has_more": False})
    publisher.create_commitment_row = AsyncMock(return_value="new-notion-id")
    publisher.update_commitment_row = AsyncMock()
    return publisher


class TestExtractHelpers:
    def test_extract_select(self) -> None:
        props = {"Status": {"select": {"name": "Completed"}}}
        assert NotionSync._extract_select(props, "Status") == "Completed"

    def test_extract_select_missing(self) -> None:
        assert NotionSync._extract_select({}, "Status") is None

    def test_extract_select_null(self) -> None:
        props = {"Status": {"select": None}}
        assert NotionSync._extract_select(props, "Status") is None

    def test_extract_priority(self) -> None:
        props = {"Priority": {"select": {"name": "P2"}}}
        assert NotionSync._extract_priority(props, "Priority") == 2

    def test_extract_priority_invalid(self) -> None:
        props = {"Priority": {"select": {"name": "High"}}}
        assert NotionSync._extract_priority(props, "Priority") is None


class TestPushToNotion:
    @pytest.mark.asyncio
    async def test_creates_row_and_stores_page_id(self) -> None:
        publisher = _make_publisher()
        sync = NotionSync(publisher)
        commitment = _make_commitment()
        result = SyncResult()

        await sync._push_to_notion(commitment, result)

        publisher.create_commitment_row.assert_awaited_once()
        assert commitment.notion_page_id is not None
        assert result.created_in_notion == 1

    @pytest.mark.asyncio
    async def test_handles_publish_error(self) -> None:
        publisher = _make_publisher()
        publisher.create_commitment_row = AsyncMock(
            side_effect=RuntimeError("Notion down")
        )
        sync = NotionSync(publisher)
        commitment = _make_commitment()
        result = SyncResult()

        await sync._push_to_notion(commitment, result)

        assert commitment.notion_page_id is None
        assert result.created_in_notion == 0
        assert len(result.errors) == 1


class TestResolveConflict:
    @pytest.mark.asyncio
    async def test_local_newer_pushes_to_notion(self) -> None:
        publisher = _make_publisher()
        sync = NotionSync(publisher)
        db = MagicMock()

        commitment = _make_commitment(
            notion_page_id="notion-123",
            status=CommitmentStatus.COMPLETED,
            updated_at=datetime(2026, 4, 18, tzinfo=timezone.utc),
        )
        notion_row = _make_notion_row(
            "notion-123",
            status="Pending",
            last_edited="2026-04-17T00:00:00.000Z",
        )
        result = SyncResult()

        await sync._resolve_conflict(db, commitment, notion_row, result)

        publisher.update_commitment_row.assert_awaited_once()
        assert result.updated_in_notion == 1

    @pytest.mark.asyncio
    async def test_notion_newer_pulls_locally(self) -> None:
        publisher = _make_publisher()
        sync = NotionSync(publisher)
        db = MagicMock()

        commitment = _make_commitment(
            notion_page_id="notion-123",
            status=CommitmentStatus.PENDING,
            priority=3,
            updated_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )
        notion_row = _make_notion_row(
            "notion-123",
            status="Completed",
            priority="P1",
            last_edited="2026-04-18T00:00:00.000Z",
        )
        result = SyncResult()

        await sync._resolve_conflict(db, commitment, notion_row, result)

        assert commitment.status == CommitmentStatus.COMPLETED
        assert commitment.priority == 1
        assert result.updated_locally == 1
        publisher.update_commitment_row.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_status_no_update(self) -> None:
        publisher = _make_publisher()
        sync = NotionSync(publisher)
        db = MagicMock()

        commitment = _make_commitment(
            notion_page_id="notion-123",
            status=CommitmentStatus.PENDING,
            priority=3,
            updated_at=datetime(2026, 4, 18, tzinfo=timezone.utc),
        )
        notion_row = _make_notion_row(
            "notion-123",
            status="Pending",
            priority="P3",
            last_edited="2026-04-17T00:00:00.000Z",
        )
        result = SyncResult()

        await sync._resolve_conflict(db, commitment, notion_row, result)

        # Nothing changed — status and priority match
        assert result.updated_in_notion == 0
        publisher.update_commitment_row.assert_not_awaited()


class TestSyncCommitments:
    @pytest.mark.asyncio
    async def test_full_sync_creates_and_resolves(self) -> None:
        publisher = _make_publisher()
        sync = NotionSync(publisher)

        user_id = uuid.uuid4()
        new_commitment = _make_commitment(user_id=user_id, notion_page_id=None)
        linked_commitment = _make_commitment(
            user_id=user_id,
            notion_page_id="existing-notion-id",
            status=CommitmentStatus.PENDING,
            updated_at=datetime(2026, 4, 18, tzinfo=timezone.utc),
        )

        # Mock DB query
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            new_commitment, linked_commitment,
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        # Mock Notion query returning one matching row
        notion_rows = [
            _make_notion_row(
                "existing-notion-id",
                status="Pending",
                last_edited="2026-04-17T00:00:00.000Z",
            ),
        ]
        with patch.object(sync, "_get_notion_commitments", new=AsyncMock(return_value=notion_rows)):
            result = await sync.sync_commitments(mock_db, user_id)

        assert result.created_in_notion == 1  # new_commitment pushed
        assert result.errors == []
