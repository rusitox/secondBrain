"""Integration tests for Slack connector (HTTP mocked with respx)."""
from typing import List, Optional

import pytest
import respx
from httpx import Response

from app.api.schemas.voice import TranscribeResponse
from app.services.connectors.slack import SlackConnector, SLACK_API_URL
from app.services.voice.transcriber import WhisperTranscriber


@pytest.fixture
def connector() -> SlackConnector:
    return SlackConnector()


class _FakeTranscriber(WhisperTranscriber):
    """Test double: no network, no Whisper cost — records what it was asked to transcribe."""

    def __init__(self, transcript: str = "Hola equipo", raise_error: bool = False) -> None:
        super().__init__(mode="api", model_name="base", openai_api_key="")
        self.transcript = transcript
        self.raise_error = raise_error
        self.calls: List[str] = []

    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm", language: Optional[str] = None,
    ) -> TranscribeResponse:
        self.calls.append(filename)
        if self.raise_error:
            raise RuntimeError("transcription failed")
        return TranscribeResponse(transcript=self.transcript, language="es", duration_seconds=1.5)


def _audio_file(
    file_id: str = "F001",
    url: str = "https://files.slack.com/files-pri/T1-F001/voice.m4a",
    size: int = 1000,
    mimetype: str = "audio/mp4",
):
    return {"id": file_id, "mimetype": mimetype, "url_private": url, "size": size, "name": "voice.m4a"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _channels_response(channels, next_cursor=""):
    return Response(200, json={
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": next_cursor},
    })


def _history_response(messages, next_cursor=""):
    return Response(200, json={
        "ok": True,
        "messages": messages,
        "response_metadata": {"next_cursor": next_cursor},
    })


def _replies_response(messages, next_cursor=""):
    return Response(200, json={
        "ok": True,
        "messages": messages,
        "response_metadata": {"next_cursor": next_cursor},
    })


def _user_response(uid, display_name="", real_name=""):
    return Response(200, json={
        "ok": True,
        "user": {"profile": {"display_name": display_name, "real_name": real_name}},
    })


# ---------------------------------------------------------------------------
# Basic fetch
# ---------------------------------------------------------------------------

class TestSlackConnectorBasic:
    @respx.mock
    async def test_fetch_messages(self, connector: SlackConnector) -> None:
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Hello team!", "user": "U001", "ts": "1705312000.000"},
                {"text": "Any updates?", "user": "U002", "ts": "1705312100.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 2
        assert items[0].content == "Hello team!"
        assert items[0].source_id == "C001:1705312000.000"
        assert items[0].metadata["channel"] == "general"
        assert items[0].metadata["type"] == "message"

    @respx.mock
    async def test_empty_messages_skipped(self, connector: SlackConnector) -> None:
        """Messages with no text are excluded from results."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "", "user": "U001", "ts": "1705312000.000"},
                {"text": "   ", "user": "U001", "ts": "1705312001.000"},
                {"text": "Real message", "user": "U001", "ts": "1705312002.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 1
        assert items[0].content == "Real message"

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: SlackConnector) -> None:
        """oldest param is sent when since is provided."""
        from datetime import datetime, timezone
        since = datetime(2024, 1, 10, tzinfo=timezone.utc)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "test"}]),
        )
        history_route = respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001"),
        )

        await connector.fetch_items(access_token="xoxb-test", since=since)
        assert "oldest" in str(history_route.calls[0].request.url)


# ---------------------------------------------------------------------------
# Author resolution
# ---------------------------------------------------------------------------

class TestAuthorResolution:
    @respx.mock
    async def test_display_name_used_when_set(self, connector: SlackConnector) -> None:
        """display_name takes precedence over real_name."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Hey!", "user": "U001", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice D.", real_name="Alice Doe"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert items[0].metadata["author"] == "Alice D."
        assert items[0].metadata["author_id"] == "U001"

    @respx.mock
    async def test_real_name_fallback_when_display_name_empty(
        self, connector: SlackConnector
    ) -> None:
        """real_name is used when display_name is empty."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Hey!", "user": "U002", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U002", display_name="", real_name="Bob Smith"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert items[0].metadata["author"] == "Bob Smith"

    @respx.mock
    async def test_uid_fallback_when_users_info_fails(self, connector: SlackConnector) -> None:
        """Raw user ID is used when users.info call fails."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Hey!", "user": "U999", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=Response(200, json={"ok": False, "error": "user_not_found"}),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        # Should not crash; falls back to raw uid
        assert items[0].metadata["author"] == "U999"

    @respx.mock
    async def test_user_ids_deduplicated_across_channels(self, connector: SlackConnector) -> None:
        """users.info is called once per unique user ID, not once per message."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([
                {"id": "C001", "name": "ch1"},
                {"id": "C002", "name": "ch2"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "msg", "user": "U001", "ts": "1000.000"},
            ]),
        )
        users_route = respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        await connector.fetch_items(access_token="xoxb-test")
        # U001 appears in both channels but users.info should only be called once
        assert len(users_route.calls) == 1


# ---------------------------------------------------------------------------
# Thread replies
# ---------------------------------------------------------------------------

class TestThreadReplies:
    @respx.mock
    async def test_thread_replies_fetched(self, connector: SlackConnector) -> None:
        """conversations.replies is called for messages with reply_count > 0."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {
                    "text": "Parent message",
                    "user": "U001",
                    "ts": "1000.000",
                    "thread_ts": "1000.000",
                    "reply_count": 2,
                },
            ]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.replies").mock(
            return_value=_replies_response([
                {"text": "Parent message", "user": "U001", "ts": "1000.000", "thread_ts": "1000.000"},
                {"text": "Reply one", "user": "U002", "ts": "1001.000", "thread_ts": "1000.000"},
                {"text": "Reply two", "user": "U001", "ts": "1002.000", "thread_ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        # Parent + 2 replies = 3 items
        assert len(items) == 3
        contents = [i.content for i in items]
        assert "Parent message" in contents
        assert "Reply one" in contents
        assert "Reply two" in contents

    @respx.mock
    async def test_thread_parent_not_duplicated(self, connector: SlackConnector) -> None:
        """The parent message is included once — not duplicated from conversations.replies."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Parent", "user": "U001", "ts": "1000.000",
                 "thread_ts": "1000.000", "reply_count": 1},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.replies").mock(
            return_value=_replies_response([
                {"text": "Parent", "user": "U001", "ts": "1000.000", "thread_ts": "1000.000"},
                {"text": "Reply", "user": "U002", "ts": "1001.000", "thread_ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        parent_items = [i for i in items if i.source_id == "C001:1000.000"]
        assert len(parent_items) == 1  # exactly once

    @respx.mock
    async def test_replies_tagged_with_is_thread_reply(self, connector: SlackConnector) -> None:
        """Thread replies have is_thread_reply=True in metadata."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Parent", "user": "U001", "ts": "1000.000",
                 "thread_ts": "1000.000", "reply_count": 1},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.replies").mock(
            return_value=_replies_response([
                {"text": "Parent", "user": "U001", "ts": "1000.000", "thread_ts": "1000.000"},
                {"text": "Reply", "user": "U002", "ts": "1001.000", "thread_ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        reply = next(i for i in items if i.source_id == "C001:1001.000")
        assert reply.metadata["is_thread_reply"] is True
        assert reply.metadata["thread_ts"] == "1000.000"

    @respx.mock
    async def test_no_replies_fetched_for_regular_messages(self, connector: SlackConnector) -> None:
        """conversations.replies is NOT called for messages without replies."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Just a message", "user": "U001", "ts": "1000.000"},
            ]),
        )
        replies_route = respx.get(f"{SLACK_API_URL}/conversations.replies").mock(
            return_value=_replies_response([]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        await connector.fetch_items(access_token="xoxb-test")
        assert len(replies_route.calls) == 0

    @respx.mock
    async def test_thread_reply_error_does_not_crash(self, connector: SlackConnector) -> None:
        """If conversations.replies fails, the parent message is still returned."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Parent", "user": "U001", "ts": "1000.000",
                 "thread_ts": "1000.000", "reply_count": 3},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.replies").mock(
            return_value=Response(200, json={"ok": False, "error": "channel_not_found"}),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 1
        assert items[0].content == "Parent"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    @respx.mock
    async def test_cursor_pagination_channels(self, connector: SlackConnector) -> None:
        """Follows cursor pagination for channel listing."""
        call_count = 0

        def channel_handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _channels_response([{"id": "C001", "name": "ch1"}], next_cursor="page2")
            return _channels_response([{"id": "C002", "name": "ch2"}])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001"),
        )

        await connector.fetch_items(access_token="xoxb-test")
        assert call_count == 2

    @respx.mock
    async def test_cursor_pagination_messages(self, connector: SlackConnector) -> None:
        """Follows cursor pagination within channel history."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        page = 0

        def history_handler(request):
            nonlocal page
            page += 1
            if page == 1:
                return _history_response(
                    [{"text": "msg1", "user": "U001", "ts": "1000.000"}],
                    next_cursor="p2",
                )
            return _history_response(
                [{"text": "msg2", "user": "U001", "ts": "1001.000"}],
            )

        respx.get(f"{SLACK_API_URL}/conversations.history").mock(side_effect=history_handler)
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Rate limiting and error handling
# ---------------------------------------------------------------------------

class TestRateLimitAndErrors:
    @respx.mock
    async def test_rate_limit_retry(self, connector: SlackConnector) -> None:
        """Retries on 429 with Retry-After header."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Response(429, headers={"Retry-After": "0.01"})
            return _channels_response([{"id": "C001", "name": "test"}])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(return_value=_user_response("U001"))

        await connector.fetch_items(access_token="xoxb-test")
        assert call_count == 2

    @respx.mock
    async def test_not_in_channel_skipped(self, connector: SlackConnector) -> None:
        """not_in_channel error causes the channel to be silently skipped."""
        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([
                {"id": "C001", "name": "accessible"},
                {"id": "C002", "name": "restricted"},
            ]),
        )

        def history_handler(request):
            channel = request.url.params.get("channel", "")
            if channel == "C002":
                return Response(200, json={"ok": False, "error": "not_in_channel"})
            return _history_response([{"text": "ok", "user": "U001", "ts": "1000.000"}])

        respx.get(f"{SLACK_API_URL}/conversations.history").mock(side_effect=history_handler)
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        channels = {i.metadata["channel"] for i in items}
        assert "restricted" not in channels
        assert "accessible" in channels


# ---------------------------------------------------------------------------
# User Token / DM access
# ---------------------------------------------------------------------------

class TestUserTokenAndDMs:
    @respx.mock
    async def test_user_token_passed_as_access_token_fetches_dms(
        self, connector: SlackConnector
    ) -> None:
        """When access_token is a User Token, im/mpim channels are included."""
        user_token = "xoxp-test-user-token"

        # List channels called twice: once for public/private, once for im/mpim
        call_count = 0

        def channel_list_handler(request):
            nonlocal call_count
            call_count += 1
            types = request.url.params.get("types", "")
            if "im" in types:
                return _channels_response([{"id": "D001", "name": "dm-with-bob"}])
            return _channels_response([{"id": "C001", "name": "general"}])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_list_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Channel message", "user": "U001", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token=user_token)
        # Two calls: one for channels, one for im/mpim
        assert call_count == 2
        channel_ids = {i.metadata["channel_id"] for i in items}
        assert "C001" in channel_ids
        assert "D001" in channel_ids

    @respx.mock
    async def test_separate_user_token_fetches_dms(self, connector: SlackConnector) -> None:
        """Bot Token for channels + separate User Token for DMs."""
        bot_token = "xoxb-bot-token"
        user_token = "xoxp-user-token"

        call_count = 0

        def channel_list_handler(request):
            nonlocal call_count
            call_count += 1
            auth = request.headers.get("Authorization", "")
            types = request.url.params.get("types", "")
            if "im" in types:
                # Must use user_token for DMs
                assert "xoxp-user-token" in auth
                return _channels_response([{"id": "D001", "name": "dm"}])
            else:
                assert "xoxb-bot-token" in auth
                return _channels_response([{"id": "C001", "name": "general"}])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_list_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "msg", "user": "U001", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token=bot_token, user_token=user_token)
        assert call_count == 2
        channel_ids = {i.metadata["channel_id"] for i in items}
        assert "C001" in channel_ids
        assert "D001" in channel_ids

    @respx.mock
    async def test_bot_token_only_no_dm_fetch(self, connector: SlackConnector) -> None:
        """With Bot Token only, im/mpim channels are NOT requested."""
        call_count = 0

        def channel_list_handler(request):
            nonlocal call_count
            call_count += 1
            return _channels_response([{"id": "C001", "name": "general"}])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_list_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(return_value=_user_response("U001"))

        await connector.fetch_items(access_token="xoxb-bot-token")
        # Only one call — channel types only, no im/mpim
        assert call_count == 1

    @respx.mock
    async def test_dm_messages_tagged_as_is_dm(self, connector: SlackConnector) -> None:
        """Messages from DM channels have is_dm=True in metadata."""
        call_count = 0

        def channel_list_handler(request):
            nonlocal call_count
            call_count += 1
            types = request.url.params.get("types", "")
            if "im" in types:
                return _channels_response([{"id": "D001", "name": "bob"}])
            return _channels_response([])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_list_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Hey!", "user": "U002", "ts": "1000.000"},
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U002", display_name="Bob"),
        )

        items = await connector.fetch_items(access_token="xoxp-user-token")
        dm_items = [i for i in items if i.metadata.get("channel_id") == "D001"]
        assert len(dm_items) == 1
        assert dm_items[0].metadata["is_dm"] is True


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

class TestTokenValidation:
    @respx.mock
    async def test_validate_token_valid(self, connector: SlackConnector) -> None:
        respx.post(f"{SLACK_API_URL}/auth.test").mock(
            return_value=Response(200, json={"ok": True, "user_id": "U001"}),
        )
        assert await connector.validate_token("xoxb-valid") is True

    @respx.mock
    async def test_validate_token_invalid(self, connector: SlackConnector) -> None:
        respx.post(f"{SLACK_API_URL}/auth.test").mock(
            return_value=Response(200, json={"ok": False, "error": "invalid_auth"}),
        )
        assert await connector.validate_token("xoxb-bad") is False

    @respx.mock
    async def test_validate_token_http_error(self, connector: SlackConnector) -> None:
        """HTTP error during auth.test returns False without raising."""
        respx.post(f"{SLACK_API_URL}/auth.test").mock(return_value=Response(500))
        assert await connector.validate_token("xoxb-bad") is False


# ---------------------------------------------------------------------------
# Audio message transcription
# ---------------------------------------------------------------------------

class TestAudioTranscription:
    @respx.mock
    async def test_voice_message_without_text_transcribed(self) -> None:
        """A voice note (no text, one audio file) is ingested using the transcript as content."""
        transcriber = _FakeTranscriber(transcript="Hola equipo, les mando esto por audio")
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"user": "U001", "ts": "1000.000", "files": [_audio_file()]},
            ]),
        )
        respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(200, content=b"fake-audio-bytes"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 1
        assert items[0].content == "Hola equipo, les mando esto por audio"
        assert items[0].metadata["has_audio"] is True
        assert transcriber.calls == ["voice.m4a"]

    @respx.mock
    async def test_text_and_audio_combined(self) -> None:
        """A message with both text and an audio attachment merges both into content."""
        transcriber = _FakeTranscriber(transcript="y el audio dice esto")
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "Mirá esto", "user": "U001", "ts": "1000.000", "files": [_audio_file()]},
            ]),
        )
        respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(200, content=b"fake-audio-bytes"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert "Mirá esto" in items[0].content
        assert "y el audio dice esto" in items[0].content

    @respx.mock
    async def test_non_audio_file_ignored(self) -> None:
        """A non-audio attachment (e.g. an image) is not sent to the transcriber."""
        transcriber = _FakeTranscriber()
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {
                    "text": "check this out",
                    "user": "U001",
                    "ts": "1000.000",
                    "files": [_audio_file(mimetype="image/png", url="https://files.slack.com/img.png")],
                },
            ]),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert items[0].content == "check this out"
        assert items[0].metadata["has_audio"] is False
        assert transcriber.calls == []

    @respx.mock
    async def test_oversized_audio_skipped_without_download(self) -> None:
        """A file over voice_max_audio_mb is never downloaded or transcribed."""
        transcriber = _FakeTranscriber()
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"user": "U001", "ts": "1000.000", "files": [_audio_file(size=100 * 1024 * 1024)]},
            ]),
        )
        download_route = respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(200, content=b"fake-audio-bytes"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(download_route.calls) == 0
        assert transcriber.calls == []
        # No text and no transcript — same as a file-only message today: skipped.
        assert len(items) == 0

    @respx.mock
    async def test_download_failure_does_not_crash_sync(self) -> None:
        """A 403 (e.g. missing files:read scope) on download is logged, not fatal."""
        transcriber = _FakeTranscriber()
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "still here", "user": "U001", "ts": "1000.000", "files": [_audio_file()]},
                {"text": "other message", "user": "U001", "ts": "1001.000"},
            ]),
        )
        respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(403, content=b"missing_scope"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 2
        assert items[0].content == "still here"  # text kept even though transcription failed

    @respx.mock
    async def test_transcription_error_does_not_crash_sync(self) -> None:
        """The transcriber raising does not take down the whole sync."""
        transcriber = _FakeTranscriber(raise_error=True)
        connector = SlackConnector(transcriber=transcriber)

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(
            return_value=_channels_response([{"id": "C001", "name": "general"}]),
        )
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"text": "hola", "user": "U001", "ts": "1000.000", "files": [_audio_file()]},
            ]),
        )
        respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(200, content=b"fake-audio-bytes"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token="xoxb-test")
        assert len(items) == 1
        assert items[0].content == "hola"

    @respx.mock
    async def test_dm_audio_downloaded_with_dm_token(self) -> None:
        """Audio in a DM is downloaded using the User Token, not the Bot Token."""
        transcriber = _FakeTranscriber(transcript="mensaje de voz en el dm")
        connector = SlackConnector(transcriber=transcriber)
        bot_token = "xoxb-bot-token"
        user_token = "xoxp-user-token"

        def channel_list_handler(request):
            types = request.url.params.get("types", "")
            if "im" in types:
                return _channels_response([{"id": "D001", "name": "dm"}])
            return _channels_response([])

        respx.get(f"{SLACK_API_URL}/conversations.list").mock(side_effect=channel_list_handler)
        respx.get(f"{SLACK_API_URL}/conversations.history").mock(
            return_value=_history_response([
                {"user": "U001", "ts": "1000.000", "files": [_audio_file()]},
            ]),
        )
        download_route = respx.get("https://files.slack.com/files-pri/T1-F001/voice.m4a").mock(
            return_value=Response(200, content=b"fake-audio-bytes"),
        )
        respx.get(f"{SLACK_API_URL}/users.info").mock(
            return_value=_user_response("U001", display_name="Alice"),
        )

        items = await connector.fetch_items(access_token=bot_token, user_token=user_token)
        assert len(items) == 1
        assert items[0].content == "mensaje de voz en el dm"
        auth_header = download_route.calls[0].request.headers.get("Authorization", "")
        assert user_token in auth_header
        assert bot_token not in auth_header
