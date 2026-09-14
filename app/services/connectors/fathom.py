"""Fathom connector for meeting transcripts.

Fathom has no public REST API (api.fathom.video is NXDOMAIN), but it does
expose an official remote MCP server at FATHOM_MCP_URL, authenticated with
a bearer API key (generate one at developers.fathom.ai -> Quickstart) —
same transport/auth shape the I+D platform integration already speaks
(app.services.agent.knowledge.rd_agent), via strands.tools.mcp.MCPClient.

Deliberately NOT an LLM-driven agent like rd_agent.py: syncing Fathom is a
deterministic ETL step ("fetch meetings since last_sync_at"), not an
open-ended question needing reasoning over a tool surface, so this calls
list_meetings/get_meeting_summary directly via MCPClient.call_tool_async
and returns ConnectorItems — same shape every other connector produces,
so it plugs into the existing SyncScheduler with no new scheduling code.

scripts/sync_fathom_incremental.py remains available for manual one-off
backfills; this connector is what the scheduler picks up automatically.
"""
import logging
import re
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

FATHOM_MCP_URL = "https://api.fathom.ai/mcp"
MEETINGS_PER_PAGE = 10  # matches list_meetings' own "~10 results/page"

# Fallback parser for list_meetings' text rendering, e.g.:
#   "- Team Sync | 2026-09-11 | id: 182274022 | url: https://... | recorded by X"
# Used only when the tool result has no structuredContent — see _parse_meetings.
_MEETING_LINE_RE = re.compile(
    r"^-\s*(?P<title>.+?)\s*\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*id:\s*(?P<id>\d+)"
    r"\s*\|\s*url:\s*(?P<url>\S+)",
)


def _text_from_result(result: Mapping[str, Any]) -> str:
    """Join every text content block of an MCP tool result."""
    parts = [
        block.get("text", "")
        for block in result.get("content", []) or []
        if block.get("text")
    ]
    return "\n".join(parts).strip()


def _parse_meetings(result: Mapping[str, Any]) -> "tuple[List[Dict[str, str]], Optional[str]]":
    """Extract (meetings, next_cursor) from a list_meetings tool result.

    Prefers structuredContent (a proper JSON list, if the server provides
    one); falls back to regex-parsing the text rendering otherwise.
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        meetings = structured.get("meetings") or structured.get("results") or []
        if isinstance(meetings, list) and meetings:
            parsed = [
                {
                    "recording_id": str(m.get("recording_id") or m.get("id")),
                    "title": m.get("title", "Meeting"),
                    "date": m.get("date") or m.get("created_at", "")[:10],
                    "url": m.get("url", ""),
                }
                for m in meetings
                if m.get("recording_id") or m.get("id")
            ]
            return parsed, structured.get("next_cursor")

    text = _text_from_result(result)
    parsed = []
    for line in text.splitlines():
        m = _MEETING_LINE_RE.match(line.strip())
        if m:
            parsed.append({
                "recording_id": m.group("id"),
                "title": m.group("title"),
                "date": m.group("date"),
                "url": m.group("url"),
            })
    return parsed, None


class FathomConnector(BaseConnector):
    """Connector for Fathom meeting transcripts, via Fathom's MCP server."""

    @property
    def platform(self) -> str:
        return "fathom"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
        **kwargs: Any,
    ) -> List[ConnectorItem]:
        """Fetch meeting summaries via Fathom's MCP server.

        access_token is the Fathom API key (stored as any other connector's
        access_token — see Integration.access_token), not an OAuth token.
        """
        from strands.tools.mcp import MCPClient

        client = MCPClient(
            url=FATHOM_MCP_URL, headers={"Authorization": f"Bearer {access_token}"},
        )
        client.start()
        try:
            items: List[ConnectorItem] = []
            cursor: Optional[str] = None

            while True:
                args: Dict[str, Any] = {"max_pages": 1}
                if since is not None:
                    args["created_after"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
                if cursor:
                    args["cursor"] = cursor

                list_result = await client.call_tool_async(
                    str(uuid.uuid4()), "list_meetings", args,
                )
                if list_result.get("status") == "error":
                    raise RuntimeError(f"Fathom list_meetings failed: {_text_from_result(list_result)}")

                meetings, cursor = _parse_meetings(list_result)

                for meeting in meetings:
                    summary_result = await client.call_tool_async(
                        str(uuid.uuid4()), "get_meeting_summary",
                        {"recording_id": int(meeting["recording_id"])},
                    )
                    if summary_result.get("status") == "error":
                        logger.warning(
                            "Fathom: could not fetch summary for meeting %s: %s",
                            meeting["recording_id"], _text_from_result(summary_result),
                        )
                        continue

                    content = _text_from_result(summary_result)
                    if not content:
                        continue

                    items.append(ConnectorItem(
                        content=content,
                        source_id=meeting["recording_id"],
                        metadata={
                            "title": meeting["title"],
                            "date": meeting["date"],
                            "recording_url": meeting["url"] or f"https://fathom.video/calls/{meeting['recording_id']}",
                            "type": "meeting",
                        },
                    ))

                if not cursor:
                    break

            logger.info("Fathom: fetched %d meetings", len(items))
            return items
        finally:
            client.stop(*sys.exc_info())

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity with a minimal list_meetings call."""
        from strands.tools.mcp import MCPClient

        client = MCPClient(
            url=FATHOM_MCP_URL, headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            client.start()
            result = await client.call_tool_async(
                str(uuid.uuid4()), "list_meetings", {"max_pages": 1},
            )
            return result.get("status") != "error"
        except Exception:
            return False
        finally:
            client.stop(*sys.exc_info())
