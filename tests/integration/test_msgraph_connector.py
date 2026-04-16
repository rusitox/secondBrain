"""Integration tests for MSGraph connector (HTTP mocked with respx)."""
import pytest
import respx
from httpx import Response

from app.services.connectors.msgraph import MSGraphConnector, GRAPH_BASE_URL


@pytest.fixture
def connector() -> MSGraphConnector:
    return MSGraphConnector()


class TestMSGraphConnector:
    @respx.mock
    async def test_fetch_emails(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(
            200,
            json={
                "value": [
                    {
                        "id": "msg-001",
                        "subject": "Budget Review",
                        "body": {"content": "Please review the Q4 budget."},
                        "from": {"emailAddress": {"address": "alice@corp.com"}},
                        "receivedDateTime": "2024-01-15T10:00:00Z",
                    },
                ],
            },
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/events").mock(return_value=Response(
            200, json={"value": []},
        ))

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].source_id == "msg-001"
        assert "Budget Review" in items[0].content
        assert items[0].metadata["author"] == "alice@corp.com"
        assert items[0].metadata["type"] == "email"

    @respx.mock
    async def test_fetch_calendar_events(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(
            200, json={"value": []},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/events").mock(return_value=Response(
            200,
            json={
                "value": [
                    {
                        "id": "evt-001",
                        "subject": "Sprint Planning",
                        "body": {"content": "Review sprint goals."},
                        "start": {"dateTime": "2024-01-15T14:00:00"},
                        "end": {"dateTime": "2024-01-15T15:00:00"},
                        "organizer": {"emailAddress": {"address": "bob@corp.com"}},
                        "attendees": [
                            {"emailAddress": {"address": "alice@corp.com"}},
                        ],
                    },
                ],
            },
        ))

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].source_id == "evt-001"
        assert items[0].metadata["type"] == "calendar_event"
        assert "alice@corp.com" in items[0].metadata["attendees"]

    @respx.mock
    async def test_pagination(self, connector: MSGraphConnector) -> None:
        """Should follow @odata.nextLink for pagination."""
        page2_url = f"{GRAPH_BASE_URL}/me/messages/next-page"
        call_count = 0

        def messages_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(200, json={
                    "value": [{"id": "msg-1", "subject": "First", "body": {"content": "Page 1"},
                               "from": {"emailAddress": {"address": "a@b.com"}},
                               "receivedDateTime": "2024-01-01T00:00:00Z"}],
                    "@odata.nextLink": page2_url,
                })
            return Response(200, json={
                "value": [{"id": "msg-2", "subject": "Second", "body": {"content": "Page 2"},
                           "from": {"emailAddress": {"address": "c@d.com"}},
                           "receivedDateTime": "2024-01-02T00:00:00Z"}],
            })

        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(side_effect=messages_handler)
        respx.get(page2_url).mock(side_effect=messages_handler)
        respx.get(f"{GRAPH_BASE_URL}/me/events").mock(return_value=Response(
            200, json={"value": []},
        ))

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 2

    @respx.mock
    async def test_validate_token_valid(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me").mock(return_value=Response(200, json={"id": "user1"}))
        assert await connector.validate_token("valid-token") is True

    @respx.mock
    async def test_validate_token_invalid(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me").mock(return_value=Response(401))
        assert await connector.validate_token("bad-token") is False

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: MSGraphConnector) -> None:
        """Should pass $filter when since is provided."""
        from datetime import datetime, timezone
        since = datetime(2024, 1, 10, tzinfo=timezone.utc)

        route = respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(
            200, json={"value": []},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/events").mock(return_value=Response(
            200, json={"value": []},
        ))

        await connector.fetch_items(access_token="token", since=since)
        # Verify $filter was passed (URL-encoded as %24filter)
        call = route.calls[0]
        assert "%24filter" in str(call.request.url) or "$filter" in str(call.request.url)
