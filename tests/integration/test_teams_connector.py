"""Integration tests for Teams connector (HTTP mocked with respx)."""
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from app.services.connectors.teams import TeamsConnector, GRAPH_BASE_URL


@pytest.fixture
def connector() -> TeamsConnector:
    return TeamsConnector()


class TestTeamsConnector:
    @respx.mock
    async def test_fetch_messages(self, connector: TeamsConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200,
            json={
                "value": [
                    {"id": "chat-001", "topic": "Project Alpha", "chatType": "group"},
                ],
            },
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-001",
                        "messageType": "message",
                        "body": {"content": "Let's finalize the proposal today."},
                        "from": {"user": {"displayName": "Alice Smith"}},
                        "createdDateTime": "2024-01-15T10:30:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].source_id == "chat-001:msg-001"
        assert "finalize the proposal" in items[0].content
        assert items[0].metadata["author"] == "Alice Smith"
        assert items[0].metadata["type"] == "teams_message"
        assert items[0].metadata["chat_topic"] == "Project Alpha"
        assert items[0].metadata["chat_type"] == "group"

    @respx.mock
    async def test_skips_system_messages(self, connector: TeamsConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200, json={"value": [{"id": "chat-001", "chatType": "group"}]},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-sys",
                        "messageType": "systemEventMessage",
                        "body": {"content": "Alice added Bob"},
                        "createdDateTime": "2024-01-15T10:00:00Z",
                    },
                    {
                        "id": "msg-real",
                        "messageType": "message",
                        "body": {"content": "Hello team"},
                        "from": {"user": {"displayName": "Bob"}},
                        "createdDateTime": "2024-01-15T10:01:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].source_id == "chat-001:msg-real"

    @respx.mock
    async def test_skips_empty_body(self, connector: TeamsConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200, json={"value": [{"id": "chat-001", "chatType": "oneOnOne"}]},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-empty",
                        "messageType": "message",
                        "body": {"content": "   "},
                        "from": {"user": {"displayName": "Alice"}},
                        "createdDateTime": "2024-01-15T10:00:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 0

    @respx.mock
    async def test_handles_null_from_field(self, connector: TeamsConnector) -> None:
        """Messages with from=None should not crash, author defaults to empty."""
        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200, json={"value": [{"id": "chat-001", "chatType": "oneOnOne"}]},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-nofrom",
                        "messageType": "message",
                        "body": {"content": "A bot message"},
                        "from": None,
                        "createdDateTime": "2024-01-15T10:00:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].metadata["author"] == ""

    @respx.mock
    async def test_pagination(self, connector: TeamsConnector) -> None:
        """Should follow @odata.nextLink for chat listing and messages."""
        page2_url = f"{GRAPH_BASE_URL}/me/chats/next-page"
        call_count = 0

        def chats_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(200, json={
                    "value": [{"id": "chat-1", "chatType": "group"}],
                    "@odata.nextLink": page2_url,
                })
            return Response(200, json={
                "value": [{"id": "chat-2", "chatType": "oneOnOne"}],
            })

        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(side_effect=chats_handler)
        respx.get(page2_url).mock(side_effect=chats_handler)
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-1/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-1",
                        "messageType": "message",
                        "body": {"content": "From chat 1"},
                        "from": {"user": {"displayName": "Alice"}},
                        "createdDateTime": "2024-01-15T10:00:00Z",
                    },
                ],
            }),
        )
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-2/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-2",
                        "messageType": "message",
                        "body": {"content": "From chat 2"},
                        "from": {"user": {"displayName": "Bob"}},
                        "createdDateTime": "2024-01-15T11:00:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 2

    @respx.mock
    async def test_validate_token_valid(self, connector: TeamsConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me").mock(
            return_value=Response(200, json={"id": "user1"}),
        )
        assert await connector.validate_token("valid-token") is True

    @respx.mock
    async def test_validate_token_invalid(self, connector: TeamsConnector) -> None:
        respx.get(f"{GRAPH_BASE_URL}/me").mock(return_value=Response(401))
        assert await connector.validate_token("bad-token") is False

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: TeamsConnector) -> None:
        """Should pass $filter with proper UTC format when since is provided."""
        since = datetime(2024, 1, 10, tzinfo=timezone.utc)

        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200, json={"value": [{"id": "chat-001", "chatType": "group"}]},
        ))
        route = respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={"value": []}),
        )

        await connector.fetch_items(access_token="token", since=since)
        call = route.calls[0]
        url_str = str(call.request.url)
        assert "2024-01-10T00%3A00%3A00Z" in url_str or "2024-01-10T00:00:00Z" in url_str

    @respx.mock
    async def test_rate_limit_retry(self, connector: TeamsConnector) -> None:
        """Should retry on 429 with Retry-After header."""
        call_count = 0

        def rate_limit_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(429, headers={"Retry-After": "0"})
            return Response(200, json={
                "value": [{"id": "chat-001", "chatType": "group"}],
            })

        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(side_effect=rate_limit_handler)
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={"value": []}),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert call_count == 2
        assert items == []

    @respx.mock
    async def test_chat_topic_fallback(self, connector: TeamsConnector) -> None:
        """When topic is null, should fall back to chatType."""
        respx.get(f"{GRAPH_BASE_URL}/me/chats").mock(return_value=Response(
            200,
            json={"value": [{"id": "chat-001", "topic": None, "chatType": "oneOnOne"}]},
        ))
        respx.get(f"{GRAPH_BASE_URL}/me/chats/chat-001/messages").mock(
            return_value=Response(200, json={
                "value": [
                    {
                        "id": "msg-001",
                        "messageType": "message",
                        "body": {"content": "Hey there"},
                        "from": {"user": {"displayName": "Alice"}},
                        "createdDateTime": "2024-01-15T10:00:00Z",
                    },
                ],
            }),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert items[0].metadata["chat_topic"] == "oneOnOne"
