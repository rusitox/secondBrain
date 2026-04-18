"""Integration tests for Notion connector (HTTP mocked with respx)."""
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from app.services.connectors.notion import NotionConnector, NOTION_API_BASE


@pytest.fixture
def connector() -> NotionConnector:
    return NotionConnector()


def _page(page_id: str, title: str, edited: str = "2026-04-18T10:00:00.000Z") -> dict:
    """Helper to build a minimal Notion page object."""
    return {
        "object": "page",
        "id": page_id,
        "last_edited_time": edited,
        "url": "https://notion.so/" + page_id,
        "parent": {"type": "workspace"},
        "last_edited_by": {"name": "Mariano"},
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": title}]},
        },
    }


def _blocks(texts: list) -> dict:
    """Helper to build a blocks children response."""
    return {
        "results": [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": t}]},
                "has_children": False,
            }
            for t in texts
        ],
        "has_more": False,
    }


class TestFetchItems:
    @respx.mock
    async def test_fetch_single_page(self, connector: NotionConnector) -> None:
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [_page("page-001", "Test Page")],
            "has_more": False,
        }))
        respx.get(NOTION_API_BASE + "/blocks/page-001/children").mock(
            return_value=Response(200, json=_blocks(["Hello world"]))
        )

        items = await connector.fetch_items("ntn_test_token")
        assert len(items) == 1
        assert "Test Page" in items[0].content
        assert "Hello world" in items[0].content
        assert items[0].source_id == "notion:page-001"
        assert items[0].metadata["type"] == "notion_page"

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: NotionConnector) -> None:
        """Pages older than since should be excluded."""
        since = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [
                _page("page-new", "New", "2026-04-18T10:00:00.000Z"),
                _page("page-old", "Old", "2026-04-16T10:00:00.000Z"),
            ],
            "has_more": False,
        }))
        respx.get(url__startswith=NOTION_API_BASE + "/blocks/page-new/children").mock(
            return_value=Response(200, json=_blocks(["New content"]))
        )

        items = await connector.fetch_items("ntn_test", since=since)
        assert len(items) == 1
        assert items[0].source_id == "notion:page-new"

    @respx.mock
    async def test_since_boundary_includes_equal(self, connector: NotionConnector) -> None:
        """Pages edited at exactly the since timestamp should be included."""
        since = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [
                _page("page-exact", "Exact", "2026-04-17T00:00:00.000Z"),
            ],
            "has_more": False,
        }))
        respx.get(url__startswith=NOTION_API_BASE + "/blocks/page-exact/children").mock(
            return_value=Response(200, json=_blocks(["Boundary content"]))
        )

        items = await connector.fetch_items("ntn_test", since=since)
        # edited == since should NOT be excluded (uses < not <=)
        assert len(items) == 1

    @respx.mock
    async def test_fetch_database_items(self, connector: NotionConnector) -> None:
        db_obj = {
            "object": "database",
            "id": "db-001",
            "title": [{"plain_text": "My DB"}],
            "last_edited_time": "2026-04-18T10:00:00.000Z",
            "url": "https://notion.so/db-001",
            "parent": {"type": "workspace"},
            "last_edited_by": {"name": "Mariano"},
            "properties": {},
        }
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [db_obj],
            "has_more": False,
        }))
        respx.post(NOTION_API_BASE + "/databases/db-001/query").mock(
            return_value=Response(200, json={
                "results": [_page("dbpage-001", "DB Item")],
                "has_more": False,
            })
        )
        respx.get(NOTION_API_BASE + "/blocks/dbpage-001/children").mock(
            return_value=Response(200, json=_blocks(["DB content"]))
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 1
        assert items[0].metadata["type"] == "notion_database_item"
        assert items[0].metadata["database_name"] == "My DB"

    @respx.mock
    async def test_search_pagination(self, connector: NotionConnector) -> None:
        call_count = 0

        def search_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(200, json={
                    "results": [_page("p1", "Page 1")],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                })
            return Response(200, json={
                "results": [_page("p2", "Page 2")],
                "has_more": False,
            })

        respx.post(NOTION_API_BASE + "/search").mock(side_effect=search_handler)
        respx.get(NOTION_API_BASE + "/blocks/p1/children").mock(
            return_value=Response(200, json=_blocks(["Content 1"]))
        )
        respx.get(NOTION_API_BASE + "/blocks/p2/children").mock(
            return_value=Response(200, json=_blocks(["Content 2"]))
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 2
        assert call_count == 2

    @respx.mock
    async def test_skips_empty_pages(self, connector: NotionConnector) -> None:
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [_page("empty-001", "")],
            "has_more": False,
        }))
        respx.get(NOTION_API_BASE + "/blocks/empty-001/children").mock(
            return_value=Response(200, json={"results": [], "has_more": False})
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 0

    @respx.mock
    async def test_handles_block_fetch_failure(self, connector: NotionConnector) -> None:
        """If block retrieval fails for a page, skip it gracefully."""
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [_page("fail-001", "Broken Page")],
            "has_more": False,
        }))
        respx.get(NOTION_API_BASE + "/blocks/fail-001/children").mock(
            return_value=Response(403, json={"message": "forbidden"})
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 0

    @respx.mock
    async def test_nested_blocks(self, connector: NotionConnector) -> None:
        parent_blocks = {
            "results": [
                {
                    "id": "block-parent",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
                    "has_children": True,
                },
            ],
            "has_more": False,
        }
        child_blocks = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Child"}]},
                    "has_children": False,
                },
            ],
            "has_more": False,
        }
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [_page("nested-001", "Nested")],
            "has_more": False,
        }))
        respx.get(NOTION_API_BASE + "/blocks/nested-001/children").mock(
            return_value=Response(200, json=parent_blocks)
        )
        respx.get(NOTION_API_BASE + "/blocks/block-parent/children").mock(
            return_value=Response(200, json=child_blocks)
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 1
        assert "Parent" in items[0].content
        assert "Child" in items[0].content


class TestValidateToken:
    @respx.mock
    async def test_valid_token(self, connector: NotionConnector) -> None:
        respx.get(NOTION_API_BASE + "/users/me").mock(
            return_value=Response(200, json={"id": "user-1"})
        )
        assert await connector.validate_token("ntn_valid") is True

    @respx.mock
    async def test_invalid_token(self, connector: NotionConnector) -> None:
        respx.get(NOTION_API_BASE + "/users/me").mock(
            return_value=Response(401, json={"message": "unauthorized"})
        )
        assert await connector.validate_token("ntn_bad") is False


class TestRateLimit:
    @respx.mock
    async def test_retry_on_429(self, connector: NotionConnector) -> None:
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(429, headers={"Retry-After": "0.1"})
            return Response(200, json={
                "results": [_page("rl-001", "After retry")],
                "has_more": False,
            })

        respx.post(NOTION_API_BASE + "/search").mock(side_effect=handler)
        respx.get(NOTION_API_BASE + "/blocks/rl-001/children").mock(
            return_value=Response(200, json=_blocks(["Retried"]))
        )

        items = await connector.fetch_items("ntn_test")
        assert len(items) == 1
        assert call_count == 2


    @respx.mock
    async def test_retry_exhaustion_raises(self, connector: NotionConnector) -> None:
        """All retries exhausted should raise an error."""
        respx.post(NOTION_API_BASE + "/search").mock(
            return_value=Response(429, headers={"Retry-After": "0.01"})
        )

        with pytest.raises(RuntimeError):
            await connector.fetch_items("ntn_test")


class TestMetadata:
    @respx.mock
    async def test_page_metadata_fields(self, connector: NotionConnector) -> None:
        respx.post(NOTION_API_BASE + "/search").mock(return_value=Response(200, json={
            "results": [_page("meta-001", "With Meta")],
            "has_more": False,
        }))
        respx.get(NOTION_API_BASE + "/blocks/meta-001/children").mock(
            return_value=Response(200, json=_blocks(["Some text"]))
        )

        items = await connector.fetch_items("ntn_test")
        meta = items[0].metadata
        assert meta["type"] == "notion_page"
        assert meta["title"] == "With Meta"
        assert meta["author"] == "Mariano"
        assert meta["url"] == "https://notion.so/meta-001"
        assert meta["parent_type"] == "workspace"
