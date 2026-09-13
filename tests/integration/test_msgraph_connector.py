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
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
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
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
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
                        "isCancelled": False,
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
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
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
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
            200, json={"value": []},
        ))

        await connector.fetch_items(access_token="token", since=since)
        # Verify $filter was passed (URL-encoded as %24filter)
        call = route.calls[0]
        assert "%24filter" in str(call.request.url) or "$filter" in str(call.request.url)

    async def test_get_own_account_id_defaults_to_none(self, connector: MSGraphConnector) -> None:
        """MSGraphConnector doesn't implement this (no ingestion feature
        needs it yet) — BaseConnector's default must apply, not raise."""
        assert await connector.get_own_account_id("token") is None


class TestCalendarViewRecurringOccurrences:
    """Root cause of a real bug: /me/events with a start-date $filter only
    matches an event whose OWN start falls in range — for a recurring
    series, that's the series' first-ever occurrence, not whichever
    occurrence actually lands on the day being asked about. A user with
    daily/weekly recurring meetings got "no reuniones" for days that
    genuinely had several, no matter how much history had been synced.
    /me/calendarView expands recurring series into real occurrences."""

    @respx.mock
    async def test_uses_calendarview_not_events(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(200, json={"value": []}))
        events_route = respx.get(f"{GRAPH_BASE_URL}/me/events").mock(
            return_value=Response(200, json={"value": [{"id": "should-not-be-called"}]}),
        )
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(200, json={"value": []}))

        await connector.fetch_items(access_token="test-token")

        assert len(events_route.calls) == 0

    @respx.mock
    async def test_recurring_occurrence_is_captured(self, connector: MSGraphConnector) -> None:
        """A recurring series' occurrence landing on a given day has its
        own id and start time distinct from the series master — exactly
        what calendarView returns and /events couldn't find."""
        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(200, json={"value": []}))
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
            200,
            json={
                "value": [
                    {
                        "id": "occurrence-2026-09-14",
                        "subject": "Daily I+D",
                        "body": {"content": ""},
                        "start": {"dateTime": "2026-09-14T12:15:00"},
                        "end": {"dateTime": "2026-09-14T12:30:00"},
                        "organizer": {"emailAddress": {"address": "boss@corp.com"}},
                        "attendees": [],
                        "type": "occurrence",
                        "seriesMasterId": "series-master-abc",
                        "isCancelled": False,
                    },
                ],
            },
        ))

        items = await connector.fetch_items(access_token="test-token")

        calendar_items = [i for i in items if i.metadata["type"] == "calendar_event"]
        assert len(calendar_items) == 1
        assert calendar_items[0].source_id == "occurrence-2026-09-14"
        assert calendar_items[0].metadata["timestamp"] == "2026-09-14T12:15:00"

    @respx.mock
    async def test_cancelled_occurrence_is_excluded(self, connector: MSGraphConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(200, json={"value": []}))
        respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(return_value=Response(
            200,
            json={
                "value": [
                    {
                        "id": "cancelled-1",
                        "subject": "Cancelado: Daily",
                        "body": {"content": ""},
                        "start": {"dateTime": "2026-09-14T12:15:00"},
                        "end": {"dateTime": "2026-09-14T12:30:00"},
                        "organizer": {"emailAddress": {"address": "boss@corp.com"}},
                        "attendees": [],
                        "isCancelled": True,
                    },
                    {
                        "id": "kept-1",
                        "subject": "Sync I+D Recap",
                        "body": {"content": ""},
                        "start": {"dateTime": "2026-09-14T13:00:00"},
                        "end": {"dateTime": "2026-09-14T13:30:00"},
                        "organizer": {"emailAddress": {"address": "boss@corp.com"}},
                        "attendees": [],
                        "isCancelled": False,
                    },
                ],
            },
        ))

        items = await connector.fetch_items(access_token="test-token")

        calendar_items = [i for i in items if i.metadata["type"] == "calendar_event"]
        assert len(calendar_items) == 1
        assert calendar_items[0].source_id == "kept-1"

    @respx.mock
    async def test_sends_a_bounded_sliding_window_not_since(self, connector: MSGraphConnector) -> None:
        """calendarView has no open-ended "everything since X" mode — both
        startDateTime and endDateTime must be sent, as a window around
        "now", regardless of the incremental sync `since` cursor (which
        still applies to email fetching, just not to calendar)."""
        from datetime import datetime, timezone

        respx.get(f"{GRAPH_BASE_URL}/me/messages").mock(return_value=Response(200, json={"value": []}))
        route = respx.get(f"{GRAPH_BASE_URL}/me/calendarView").mock(
            return_value=Response(200, json={"value": []}),
        )

        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await connector.fetch_items(access_token="test-token", since=since)

        call = route.calls[0]
        query = str(call.request.url)
        assert "startDateTime=" in query
        assert "endDateTime=" in query
        # The window is relative to "now", not to the old `since` cursor.
        assert "2020-01-01" not in query
