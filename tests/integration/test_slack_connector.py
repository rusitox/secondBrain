"""Integration tests for Slack connector (HTTP mocked with respx)."""
import pytest
import respx
from httpx import Response

from app.services.connectors.slack import SlackConnector, SLACK_API_URL


@pytest.fixture
def connector() -> SlackConnector:
    return SlackConnector()


class TestSlackConnector:
    @respx.mock
    async def test_fetch_messages(self, connector: SlackConnector) -> None:
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(return_value=Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C001", "name": "general"}],
                "response_metadata": {"next_cursor": ""},
            },
        ))
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(return_value=Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"text": "Hello team!", "user": "U001", "ts": "1705312000.000"},
                    {"text": "Any updates?", "user": "U002", "ts": "1705312100.000"},
                ],
                "response_metadata": {"next_cursor": ""},
            },
        ))

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 2
        assert items[0].content == "Hello team!"
        assert items[0].source_id == "C001:1705312000.000"
        assert items[0].metadata["channel"] == "general"
        assert items[0].metadata["type"] == "message"

    @respx.mock
    async def test_cursor_pagination_channels(self, connector: SlackConnector) -> None:
        """Should follow cursor pagination for channel listing."""
        call_count = 0

        def channel_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(200, json={
                    "ok": True,
                    "channels": [{"id": "C001", "name": "ch1"}],
                    "response_metadata": {"next_cursor": "cursor_page2"},
                })
            return Response(200, json={
                "ok": True,
                "channels": [{"id": "C002", "name": "ch2"}],
                "response_metadata": {"next_cursor": ""},
            })

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(return_value=Response(
            200,
            json={"ok": True, "messages": [], "response_metadata": {"next_cursor": ""}},
        ))

        items = await connector.fetch_items(access_token="xoxb-test")
        assert call_count == 2  # two pages of channels

    @respx.mock
    async def test_rate_limit_retry(self, connector: SlackConnector) -> None:
        """Should retry on 429 with Retry-After header."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(429, headers={"Retry-After": "0.1"})
            return Response(200, json={
                "ok": True,
                "channels": [{"id": "C001", "name": "test"}],
                "response_metadata": {"next_cursor": ""},
            })

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(return_value=Response(
            200,
            json={"ok": True, "messages": [], "response_metadata": {"next_cursor": ""}},
        ))

        items = await connector.fetch_items(access_token="xoxb-test")
        assert call_count == 2  # first call 429, second succeeds

    @respx.mock
    async def test_validate_token_valid(self, connector: SlackConnector) -> None:
        respx.post(f"{SLACK_API_URL}/auth.test").mock(return_value=Response(
            200, json={"ok": True, "user_id": "U001"},
        ))
        assert await connector.validate_token("xoxb-valid") is True

    @respx.mock
    async def test_validate_token_invalid(self, connector: SlackConnector) -> None:
        respx.post(f"{SLACK_API_URL}/auth.test").mock(return_value=Response(
            200, json={"ok": False, "error": "invalid_auth"},
        ))
        assert await connector.validate_token("xoxb-bad") is False

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: SlackConnector) -> None:
        """Should pass oldest param when since is provided."""
        from datetime import datetime, timezone
        since = datetime(2024, 1, 10, tzinfo=timezone.utc)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(return_value=Response(
            200, json={
                "ok": True,
                "channels": [{"id": "C001", "name": "test"}],
                "response_metadata": {"next_cursor": ""},
            },
        ))
        history_route = respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=Response(200, json={
                "ok": True, "messages": [], "response_metadata": {"next_cursor": ""},
            }),
        )

        await connector.fetch_items(access_token="xoxb-test", since=since)
        call = history_route.calls[0]
        assert "oldest" in str(call.request.url)
