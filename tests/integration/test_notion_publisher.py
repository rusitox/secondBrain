"""Integration tests for NotionPublisher (HTTP mocked with respx)."""
import pytest
import respx
from httpx import Response

from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.publisher import NotionPublisher, NOTION_API_BASE


@pytest.fixture
def config() -> NotionWorkspaceConfig:
    return NotionWorkspaceConfig(
        enabled=True,
        root_page_id="root-page-id",
        commitments_db_id="commit-db-id",
        briefings_db_id="briefing-db-id",
        meeting_prep_db_id="meeting-db-id",
    )


@pytest.fixture
def publisher(config: NotionWorkspaceConfig) -> NotionPublisher:
    return NotionPublisher("ntn_test_token", config)


class TestSetupWorkspace:
    @respx.mock
    async def test_creates_root_and_databases(self) -> None:
        # Mock root page creation
        respx.post(NOTION_API_BASE + "/pages").mock(return_value=Response(200, json={
            "id": "new-root-id",
            "url": "https://notion.so/new-root-id",
        }))
        # Mock database creation (called 3 times)
        respx.post(NOTION_API_BASE + "/databases").mock(side_effect=[
            Response(200, json={"id": "comm-db-id"}),
            Response(200, json={"id": "brief-db-id"}),
            Response(200, json={"id": "meet-db-id"}),
        ])

        publisher = NotionPublisher("ntn_test", NotionWorkspaceConfig())
        config = await publisher.setup_workspace()

        assert config.enabled is True
        assert config.root_page_id == "new-root-id"
        assert config.commitments_db_id == "comm-db-id"
        assert config.briefings_db_id == "brief-db-id"
        assert config.meeting_prep_db_id == "meet-db-id"


class TestPublishBriefing:
    @respx.mock
    async def test_creates_briefing_page(self, publisher: NotionPublisher) -> None:
        route = respx.post(NOTION_API_BASE + "/pages").mock(return_value=Response(200, json={
            "id": "briefing-page-id",
            "url": "https://notion.so/briefing-page-id",
        }))

        url = await publisher.publish_briefing("## Summary\n\nAll good today.", "2026-04-18")

        assert url == "https://notion.so/briefing-page-id"
        assert route.call_count == 1

        # Verify the request body
        body = route.calls[0].request.content
        import json
        data = json.loads(body)
        assert data["parent"]["database_id"] == "briefing-db-id"
        assert data["properties"]["Name"]["title"][0]["text"]["content"] == "Briefing \u2014 2026-04-18"
        assert data["properties"]["Date"]["date"]["start"] == "2026-04-18"
        assert data["properties"]["Status"]["select"]["name"] == "Published"
        # Should have children blocks (heading + paragraph)
        assert len(data["children"]) >= 2


class TestCreateCommitmentRow:
    @respx.mock
    async def test_creates_commitment(self, publisher: NotionPublisher) -> None:
        route = respx.post(NOTION_API_BASE + "/pages").mock(return_value=Response(200, json={
            "id": "commitment-page-id",
        }))

        page_id = await publisher.create_commitment_row({
            "commitment_text": "Send report by Friday",
            "status": "pending",
            "priority": 2,
            "owner": "Mariano",
            "source": "slack",
            "due_date": "2026-04-20",
            "created_at": "2026-04-18T10:00:00Z",
        })

        assert page_id == "commitment-page-id"
        assert route.call_count == 1

        import json
        data = json.loads(route.calls[0].request.content)
        props = data["properties"]
        assert props["Name"]["title"][0]["text"]["content"] == "Send report by Friday"
        assert props["Status"]["select"]["name"] == "Pending"
        assert props["Priority"]["select"]["name"] == "P2"
        assert props["Owner"]["rich_text"][0]["text"]["content"] == "Mariano"
        assert props["Source"]["select"]["name"] == "slack"
        assert props["Due Date"]["date"]["start"] == "2026-04-20"

    @respx.mock
    async def test_creates_commitment_without_due_date(self, publisher: NotionPublisher) -> None:
        respx.post(NOTION_API_BASE + "/pages").mock(return_value=Response(200, json={
            "id": "no-due-id",
        }))

        page_id = await publisher.create_commitment_row({
            "commitment_text": "No deadline task",
            "status": "pending",
            "priority": 3,
        })

        assert page_id == "no-due-id"


class TestUpdateCommitmentRow:
    @respx.mock
    async def test_updates_status(self, publisher: NotionPublisher) -> None:
        route = respx.patch(url__startswith=NOTION_API_BASE + "/pages/").mock(
            return_value=Response(200, json={"id": "page-123"})
        )

        await publisher.update_commitment_row("page-123", {"status": "completed"})

        assert route.call_count == 1
        import json
        data = json.loads(route.calls[0].request.content)
        assert data["properties"]["Status"]["select"]["name"] == "Completed"

    @respx.mock
    async def test_updates_multiple_fields(self, publisher: NotionPublisher) -> None:
        route = respx.patch(url__startswith=NOTION_API_BASE + "/pages/").mock(
            return_value=Response(200, json={"id": "page-123"})
        )

        await publisher.update_commitment_row("page-123", {
            "status": "completed",
            "priority": 1,
            "owner": "Alice",
        })

        import json
        data = json.loads(route.calls[0].request.content)
        assert data["properties"]["Status"]["select"]["name"] == "Completed"
        assert data["properties"]["Priority"]["select"]["name"] == "P1"
        assert data["properties"]["Owner"]["rich_text"][0]["text"]["content"] == "Alice"

    @respx.mock
    async def test_noop_with_empty_updates(self, publisher: NotionPublisher) -> None:
        route = respx.patch(url__startswith=NOTION_API_BASE + "/pages/").mock(
            return_value=Response(200, json={})
        )

        await publisher.update_commitment_row("page-123", {})

        assert route.call_count == 0


class TestGetWorkspaceUrl:
    @respx.mock
    async def test_returns_url(self, publisher: NotionPublisher) -> None:
        respx.get(url__startswith=NOTION_API_BASE + "/pages/").mock(
            return_value=Response(200, json={"url": "https://notion.so/root-page-id"})
        )

        url = await publisher.get_workspace_url()
        assert url == "https://notion.so/root-page-id"

    async def test_returns_empty_when_no_root(self) -> None:
        config = NotionWorkspaceConfig(root_page_id=None)
        publisher = NotionPublisher("ntn_test", config)
        url = await publisher.get_workspace_url()
        assert url == ""
