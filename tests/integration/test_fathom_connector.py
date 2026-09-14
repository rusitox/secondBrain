"""Integration tests for FathomConnector — its raw data comes from Fathom's
MCP server, so MCPClient itself is mocked here (same pattern as
tests/integration/test_rd_agent.py for the I+D platform's MCP connection).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.connectors.fathom import FathomConnector, FATHOM_MCP_URL


@pytest.fixture
def connector() -> FathomConnector:
    return FathomConnector()


def _tool_result(
    text: Optional[str] = None,
    structured: Optional[Dict[str, Any]] = None,
    status: str = "success",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": status, "content": []}
    if text is not None:
        result["content"] = [{"text": text}]
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _mock_client(call_tool_results: List[Dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.start.return_value = client
    client.call_tool_async = AsyncMock(side_effect=call_tool_results)
    return client


class TestFathomConnectorPlatform:
    def test_platform_name(self, connector: FathomConnector) -> None:
        assert connector.platform == "fathom"


class TestFathomConnectorFetchItems:
    @pytest.mark.asyncio
    async def test_fetches_meeting_via_structured_content(self, connector: FathomConnector) -> None:
        list_result = _tool_result(structured={
            "meetings": [{
                "recording_id": 182274022, "title": "Team Sync",
                "date": "2026-09-11", "url": "https://fathom.video/calls/820433728",
            }],
        })
        summary_result = _tool_result(text="## Propósito\nRevisar el roadmap.")
        client = _mock_client([list_result, summary_result])

        with patch("strands.tools.mcp.MCPClient", return_value=client) as mock_cls:
            items = await connector.fetch_items(access_token="fathom-key")

        assert len(items) == 1
        assert items[0].source_id == "182274022"
        assert items[0].content == "## Propósito\nRevisar el roadmap."
        assert items[0].metadata["title"] == "Team Sync"
        assert items[0].metadata["date"] == "2026-09-11"
        assert items[0].metadata["recording_url"] == "https://fathom.video/calls/820433728"
        mock_cls.assert_called_once()
        assert mock_cls.call_args.kwargs["url"] == FATHOM_MCP_URL
        assert mock_cls.call_args.kwargs["headers"] == {"Authorization": "Bearer fathom-key"}

    @pytest.mark.asyncio
    async def test_fetches_meeting_via_text_fallback(self, connector: FathomConnector) -> None:
        """No structuredContent — falls back to parsing the text rendering."""
        list_text = (
            "Found 1 meeting(s).\n\n"
            "- Team Sync | 2026-09-11 | id: 182274022 "
            "| url: https://fathom.video/calls/820433728 | recorded by Mariano"
        )
        list_result = _tool_result(text=list_text)
        summary_result = _tool_result(text="Summary text")
        client = _mock_client([list_result, summary_result])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            items = await connector.fetch_items(access_token="fathom-key")

        assert len(items) == 1
        assert items[0].source_id == "182274022"
        assert items[0].metadata["title"] == "Team Sync"

    @pytest.mark.asyncio
    async def test_since_passed_as_created_after(self, connector: FathomConnector) -> None:
        since = datetime(2026, 9, 1, 22, 28, 59, tzinfo=timezone.utc)
        client = _mock_client([_tool_result(structured={"meetings": []})])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            await connector.fetch_items(access_token="tok", since=since)

        call_args = client.call_tool_async.call_args_list[0]
        assert call_args.args[2]["created_after"] == "2026-09-01T22:28:59Z"

    @pytest.mark.asyncio
    async def test_no_since_omits_created_after(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(structured={"meetings": []})])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            await connector.fetch_items(access_token="tok")

        call_args = client.call_tool_async.call_args_list[0]
        assert "created_after" not in call_args.args[2]

    @pytest.mark.asyncio
    async def test_pagination_follows_cursor(self, connector: FathomConnector) -> None:
        page1 = _tool_result(structured={
            "meetings": [{"recording_id": 1, "title": "M1", "date": "2026-09-01", "url": "u1"}],
            "next_cursor": "page2",
        })
        summary1 = _tool_result(text="s1")
        page2 = _tool_result(structured={
            "meetings": [{"recording_id": 2, "title": "M2", "date": "2026-09-02", "url": "u2"}],
        })
        summary2 = _tool_result(text="s2")
        client = _mock_client([page1, summary1, page2, summary2])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            items = await connector.fetch_items(access_token="tok")

        assert {i.source_id for i in items} == {"1", "2"}
        # 2 list_meetings calls + 2 get_meeting_summary calls
        assert client.call_tool_async.call_count == 4
        second_list_call = client.call_tool_async.call_args_list[2]
        assert second_list_call.args[1] == "list_meetings"
        assert second_list_call.args[2]["cursor"] == "page2"

    @pytest.mark.asyncio
    async def test_list_meetings_error_raises(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(text="unauthorized", status="error")])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            with pytest.raises(RuntimeError, match="list_meetings failed"):
                await connector.fetch_items(access_token="bad-key")

    @pytest.mark.asyncio
    async def test_summary_error_is_skipped_not_fatal(self, connector: FathomConnector) -> None:
        list_result = _tool_result(structured={
            "meetings": [{"recording_id": 1, "title": "M1", "date": "2026-09-01", "url": "u1"}],
        })
        summary_error = _tool_result(text="not found", status="error")
        client = _mock_client([list_result, summary_error])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            items = await connector.fetch_items(access_token="tok")

        assert items == []

    @pytest.mark.asyncio
    async def test_empty_summary_content_skipped(self, connector: FathomConnector) -> None:
        list_result = _tool_result(structured={
            "meetings": [{"recording_id": 1, "title": "M1", "date": "2026-09-01", "url": "u1"}],
        })
        empty_summary = _tool_result(text="")
        client = _mock_client([list_result, empty_summary])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            items = await connector.fetch_items(access_token="tok")

        assert items == []

    @pytest.mark.asyncio
    async def test_client_started_and_stopped(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(structured={"meetings": []})])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            await connector.fetch_items(access_token="tok")

        client.start.assert_called_once()
        client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_client_stopped_even_on_error(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(text="boom", status="error")])

        with patch("strands.tools.mcp.MCPClient", return_value=client):
            with pytest.raises(RuntimeError):
                await connector.fetch_items(access_token="tok")

        client.stop.assert_called_once()


class TestFathomConnectorValidateToken:
    @pytest.mark.asyncio
    async def test_validate_token_valid(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(structured={"meetings": []})])
        with patch("strands.tools.mcp.MCPClient", return_value=client):
            assert await connector.validate_token("good-key") is True

    @pytest.mark.asyncio
    async def test_validate_token_invalid(self, connector: FathomConnector) -> None:
        client = _mock_client([_tool_result(text="unauthorized", status="error")])
        with patch("strands.tools.mcp.MCPClient", return_value=client):
            assert await connector.validate_token("bad-key") is False

    @pytest.mark.asyncio
    async def test_validate_token_connection_failure(self, connector: FathomConnector) -> None:
        client = MagicMock()
        client.start.side_effect = RuntimeError("connection refused")
        with patch("strands.tools.mcp.MCPClient", return_value=client):
            assert await connector.validate_token("any-key") is False
