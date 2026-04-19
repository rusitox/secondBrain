"""Unit tests for NotionConnector (mocked HTTP)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.connectors.notion import (
    NotionConnector,
    _extract_page_metadata,
    _iso_timestamp,
    _parse_title,
)


class TestIsoTimestamp:
    def test_naive_datetime(self) -> None:
        dt = datetime(2026, 4, 18, 10, 30, 0)
        assert _iso_timestamp(dt) == "2026-04-18T10:30:00.000Z"

    def test_utc_datetime(self) -> None:
        dt = datetime(2026, 4, 18, 10, 30, 0, tzinfo=timezone.utc)
        assert _iso_timestamp(dt) == "2026-04-18T10:30:00.000Z"


class TestParseTitle:
    def test_page_with_title_property(self) -> None:
        page = {
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page"}],
                },
            },
        }
        assert _parse_title(page) == "My Page"

    def test_database_with_title_field(self) -> None:
        db = {
            "title": [{"plain_text": "My Database"}],
            "properties": {},
        }
        assert _parse_title(db) == "My Database"

    def test_no_title(self) -> None:
        assert _parse_title({"properties": {}}) == ""


class TestExtractPageMetadata:
    def test_basic_metadata(self) -> None:
        page = {
            "object": "page",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Test"}]},
            },
            "last_edited_time": "2026-04-18T10:00:00.000Z",
            "url": "https://notion.so/test",
            "parent": {"type": "workspace"},
            "last_edited_by": {"name": "Mariano"},
        }
        meta = _extract_page_metadata(page)
        assert meta["type"] == "notion_page"
        assert meta["title"] == "Test"
        assert meta["author"] == "Mariano"
        assert meta["url"] == "https://notion.so/test"
        assert meta["parent_type"] == "workspace"

    def test_tags_extraction(self) -> None:
        page = {
            "object": "page",
            "properties": {
                "Name": {"type": "title", "title": []},
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [
                        {"name": "tag1"},
                        {"name": "tag2"},
                    ],
                },
            },
            "parent": {"type": "database_id"},
            "last_edited_by": {},
        }
        meta = _extract_page_metadata(page)
        assert meta["tags"] == ["tag1", "tag2"]

    def test_database_type(self) -> None:
        db = {
            "object": "database",
            "properties": {},
            "parent": {"type": "workspace"},
            "last_edited_by": {},
        }
        meta = _extract_page_metadata(db)
        assert meta["type"] == "notion_database_item"


class TestNotionConnectorPlatform:
    def test_platform_name(self) -> None:
        connector = NotionConnector()
        assert connector.platform == "notion"


class TestNotionConnectorErrorHandling:
    """Test that 401, 403, 404 raise immediately without retries."""

    @pytest.mark.asyncio
    async def test_401_raises_token_revoked(self) -> None:
        connector = NotionConnector()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(RuntimeError, match="token is invalid or revoked"):
            await connector._api_call(
                mock_client, {"Authorization": "Bearer bad"}, "GET",
                "https://api.notion.com/v1/users/me",
            )

    @pytest.mark.asyncio
    async def test_403_raises_permission_error(self) -> None:
        connector = NotionConnector()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(RuntimeError, match="lacks permission"):
            await connector._api_call(
                mock_client, {"Authorization": "Bearer x"}, "GET",
                "https://api.notion.com/v1/pages/abc",
            )

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        connector = NotionConnector()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(RuntimeError, match="not found"):
            await connector._api_call(
                mock_client, {"Authorization": "Bearer x"}, "POST",
                "https://api.notion.com/v1/databases/abc/query",
            )
