"""Integration tests for NotionSync (Notion API mocked with respx)."""
import uuid
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response
from unittest.mock import AsyncMock, MagicMock

from app.models.commitment import Commitment, CommitmentStatus
from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.publisher import NotionPublisher, NOTION_API_BASE
from app.services.notion.sync import NotionSync


@pytest.fixture
def config() -> NotionWorkspaceConfig:
    return NotionWorkspaceConfig(
        enabled=True,
        root_page_id="root-id",
        commitments_db_id="commit-db-id",
        briefings_db_id="briefing-db-id",
        meeting_prep_db_id="meeting-db-id",
    )


@pytest.fixture
def publisher(config: NotionWorkspaceConfig) -> NotionPublisher:
    return NotionPublisher("ntn_test_token", config)


@pytest.fixture
def sync(publisher: NotionPublisher) -> NotionSync:
    return NotionSync(publisher)


def _make_commitment(**overrides) -> Commitment:
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        commitment_text="Send report",
        owner="Alice",
        status=CommitmentStatus.PENDING,
        priority=2,
        notion_page_id=None,
        due_date=None,
        created_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    c = MagicMock(spec=Commitment)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


class TestGetNotionCommitments:
    @pytest.mark.asyncio
    @respx.mock
    async def test_queries_database(self, sync: NotionSync) -> None:
        route = respx.post(
            url__startswith=NOTION_API_BASE + "/databases/"
        ).mock(return_value=Response(200, json={
            "results": [
                {
                    "id": "row-1",
                    "last_edited_time": "2026-04-17T00:00:00.000Z",
                    "properties": {
                        "Status": {"select": {"name": "Pending"}},
                        "Priority": {"select": {"name": "P2"}},
                    },
                },
            ],
            "has_more": False,
        }))

        rows = await sync._get_notion_commitments()

        assert len(rows) == 1
        assert rows[0]["id"] == "row-1"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_paginates(self, sync: NotionSync) -> None:
        respx.post(
            url__startswith=NOTION_API_BASE + "/databases/"
        ).mock(side_effect=[
            Response(200, json={
                "results": [{"id": "row-1", "properties": {}}],
                "has_more": True,
                "next_cursor": "cursor-2",
            }),
            Response(200, json={
                "results": [{"id": "row-2", "properties": {}}],
                "has_more": False,
            }),
        ])

        rows = await sync._get_notion_commitments()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_if_no_db_id(self) -> None:
        config = NotionWorkspaceConfig(commitments_db_id=None)
        publisher = NotionPublisher("ntn_test", config)
        sync = NotionSync(publisher)
        rows = await sync._get_notion_commitments()
        assert rows == []


class TestSyncCommitmentsIntegration:
    @pytest.mark.asyncio
    @respx.mock
    async def test_creates_new_commitments_in_notion(
        self, sync: NotionSync,
    ) -> None:
        user_id = uuid.uuid4()

        # Mock Notion database query (empty — no existing rows)
        respx.post(
            url__startswith=NOTION_API_BASE + "/databases/"
        ).mock(return_value=Response(200, json={
            "results": [],
            "has_more": False,
        }))

        # Mock page creation
        create_route = respx.post(NOTION_API_BASE + "/pages").mock(
            return_value=Response(200, json={"id": "new-notion-page"})
        )

        commitment = _make_commitment(user_id=user_id)

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [commitment]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await sync.sync_commitments(mock_db, user_id)

        assert result.created_in_notion == 1
        # Page ID is normalized to UUID format with dashes
        assert commitment.notion_page_id is not None
        assert create_route.call_count == 1
