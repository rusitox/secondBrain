"""Notion publisher — writes content to the assistant's workspace.

Creates and manages a page hierarchy in the user's Notion workspace:
  secondBrain (root page)
    ├── Commitments   (database)
    ├── Briefings     (database)
    └── Meeting Prep  (database)
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.notion.blocks import text_to_blocks
from app.services.notion.config import NotionWorkspaceConfig

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT = 30.0

MAX_RETRIES = 3
MAX_RATE_RETRIES = 5
BASE_DELAY = 1.0
_RATE_LIMIT = 3

# Notion API limits text.content to 2000 chars
_MAX_TEXT_LENGTH = 2000


def _rich_text_safe(text: str) -> List[Dict[str, Any]]:
    """Wrap text in a Notion rich_text array, splitting at 2000-char limit."""
    if not text:
        return []
    chunks: List[Dict[str, Any]] = []
    for i in range(0, len(text), _MAX_TEXT_LENGTH):
        chunks.append({"type": "text", "text": {"content": text[i:i + _MAX_TEXT_LENGTH]}})
    return chunks


class NotionPublisher:
    """Publishes content to the assistant's Notion workspace."""

    def __init__(self, token: str, config: NotionWorkspaceConfig) -> None:
        self._token = token
        self._config = config
        self._request_times: List[float] = []

    # ── Public API ─────────────────────────────────────────────

    async def setup_workspace(self) -> NotionWorkspaceConfig:
        """Create the root page and databases (first-time setup).

        Returns an updated config with the created IDs.
        All mutations are applied atomically — config is only updated
        after all 4 API calls succeed.
        """
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()

            # 1. Create root page
            root_page = await self._api_call(client, headers, "POST", NOTION_API_BASE + "/pages", {
                "parent": {"type": "workspace", "workspace": True},
                "icon": {"type": "emoji", "emoji": "\U0001f916"},
                "properties": {
                    "title": {"title": [{"text": {"content": "secondBrain"}}]},
                },
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": "Your AI assistant's workspace. Everything published here is managed by secondBrain."},
                            }],
                        },
                    },
                ],
            })
            root_id = root_page["id"]
            root_url = root_page.get("url", "")
            logger.info("Created root page: %s", root_id)

            # 2. Create databases
            commitments_db = await self._create_commitments_db(client, headers, root_id)
            briefings_db = await self._create_briefings_db(client, headers, root_id)
            meeting_db = await self._create_meeting_prep_db(client, headers, root_id)

            # Only update config after all calls succeed (C1 fix)
            self._config.root_page_id = root_id
            self._config.root_page_url = root_url
            self._config.commitments_db_id = commitments_db["id"]
            self._config.briefings_db_id = briefings_db["id"]
            self._config.meeting_prep_db_id = meeting_db["id"]
            self._config.enabled = True

            return self._config

    async def publish_briefing(self, briefing_text: str, date_str: str) -> str:
        """Publish a daily briefing as a page in the Briefings database.

        Args:
            briefing_text: The briefing content (markdown-ish text).
            date_str: Date string in YYYY-MM-DD format.

        Returns:
            The URL of the created Notion page.
        """
        if not self._config.briefings_db_id:
            raise RuntimeError("Briefings database not set up")

        title = "Briefing \u2014 %s" % date_str
        blocks = text_to_blocks(briefing_text)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            page = await self._api_call(client, headers, "POST", NOTION_API_BASE + "/pages", {
                "parent": {"database_id": self._config.briefings_db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Date": {"date": {"start": date_str}},
                    "Status": {"select": {"name": "Published"}},
                },
                "children": blocks[:100],  # Notion limit: 100 blocks per request
            })
            url = page.get("url", "")
            logger.info("Published briefing for %s: %s", date_str, url)
            return url

    async def create_commitment_row(self, commitment: Dict[str, Any]) -> str:
        """Create a row in the Commitments database.

        Args:
            commitment: Dict with keys: commitment_text, status, priority,
                        due_date, owner, source.

        Returns:
            The Notion page ID of the created row.
        """
        if not self._config.commitments_db_id:
            raise RuntimeError("Commitments database not set up")

        properties: Dict[str, Any] = {
            "Name": {"title": _rich_text_safe(commitment.get("commitment_text", ""))},
            "Status": {"select": {"name": _map_status(commitment.get("status", "pending"))}},
            "Priority": {"select": {"name": "P%d" % commitment.get("priority", 3)}},
            "Owner": {"rich_text": _rich_text_safe(commitment.get("owner", "unknown"))},
            "Source": {"select": {"name": commitment.get("source", "unknown")}},
            "Detected": {"date": {"start": commitment.get("created_at", datetime.now(timezone.utc).isoformat())}},
        }

        due_date = commitment.get("due_date")
        if due_date:
            properties["Due Date"] = {"date": {"start": due_date}}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            page = await self._api_call(client, headers, "POST", NOTION_API_BASE + "/pages", {
                "parent": {"database_id": self._config.commitments_db_id},
                "properties": properties,
            })
            page_id = page["id"]
            logger.info("Created commitment row: %s", page_id)
            return page_id

    async def update_commitment_row(
        self, notion_page_id: str, updates: Dict[str, Any],
    ) -> None:
        """Update properties of a commitment in Notion.

        Args:
            notion_page_id: The Notion page ID to update.
            updates: Dict of fields to update (status, priority, due_date, owner).
        """
        properties: Dict[str, Any] = {}

        if "status" in updates:
            properties["Status"] = {"select": {"name": _map_status(updates["status"])}}
        if "priority" in updates:
            properties["Priority"] = {"select": {"name": "P%d" % updates["priority"]}}
        if "due_date" in updates:
            properties["Due Date"] = {"date": {"start": updates["due_date"]} if updates["due_date"] else None}
        if "owner" in updates:
            properties["Owner"] = {"rich_text": _rich_text_safe(updates["owner"])}

        if not properties:
            return

        safe_id = quote(notion_page_id, safe="")
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            await self._api_call(
                client, headers, "PATCH",
                NOTION_API_BASE + "/pages/" + safe_id,
                {"properties": properties},
            )
            logger.info("Updated commitment row: %s", notion_page_id)

    async def publish_weekly_digest(self, digest_text: str, week_start: str, week_end: str) -> str:
        """Publish a weekly digest as a page in the Briefings database.

        Args:
            digest_text: The digest content (markdown-ish text).
            week_start: Start of week in YYYY-MM-DD format.
            week_end: End of week in YYYY-MM-DD format.

        Returns:
            The URL of the created Notion page.
        """
        if not self._config.briefings_db_id:
            raise RuntimeError("Briefings database not set up")

        title = "Weekly Digest \u2014 %s to %s" % (week_start, week_end)
        blocks = text_to_blocks(digest_text)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            page = await self._api_call(client, headers, "POST", NOTION_API_BASE + "/pages", {
                "parent": {"database_id": self._config.briefings_db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Date": {"date": {"start": week_start, "end": week_end}},
                    "Status": {"select": {"name": "Published"}},
                },
                "children": blocks[:100],
            })
            url = page.get("url", "")
            logger.info("Published weekly digest %s to %s: %s", week_start, week_end, url)
            return url

    async def publish_meeting_prep(self, title: str, prep_text: str, date_str: str) -> str:
        """Publish a meeting prep page in the Meeting Prep database.

        Args:
            title: Meeting name/topic.
            prep_text: The meeting prep content.
            date_str: Date string in YYYY-MM-DD format.

        Returns:
            The URL of the created Notion page.
        """
        if not self._config.meeting_prep_db_id:
            raise RuntimeError("Meeting Prep database not set up")

        blocks = text_to_blocks(prep_text)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            page = await self._api_call(client, headers, "POST", NOTION_API_BASE + "/pages", {
                "parent": {"database_id": self._config.meeting_prep_db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Date": {"date": {"start": date_str}},
                    "Status": {"select": {"name": "Prepared"}},
                },
                "children": blocks[:100],
            })
            url = page.get("url", "")
            logger.info("Published meeting prep '%s': %s", title, url)
            return url

    async def get_workspace_url(self) -> str:
        """Return the URL of the root workspace page."""
        if not self._config.root_page_id:
            return ""
        # Use cached URL if available
        if self._config.root_page_url:
            return self._config.root_page_url
        safe_id = quote(self._config.root_page_id, safe="")
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = self._build_headers()
            page = await self._api_call(
                client, headers, "GET",
                NOTION_API_BASE + "/pages/" + safe_id,
            )
            return page.get("url", "")

    # ── Database creation helpers ──────────────────────────────

    async def _create_commitments_db(
        self, client: httpx.AsyncClient, headers: Dict[str, str], parent_id: str,
    ) -> Dict[str, Any]:
        return await self._api_call(client, headers, "POST", NOTION_API_BASE + "/databases", {
            "parent": {"type": "page_id", "page_id": parent_id},
            "icon": {"type": "emoji", "emoji": "\U0001f4cb"},
            "title": [{"text": {"content": "Commitments"}}],
            "properties": {
                "Name": {"title": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Pending", "color": "yellow"},
                            {"name": "Completed", "color": "green"},
                            {"name": "Cancelled", "color": "red"},
                        ],
                    },
                },
                "Priority": {
                    "select": {
                        "options": [
                            {"name": "P1", "color": "red"},
                            {"name": "P2", "color": "orange"},
                            {"name": "P3", "color": "yellow"},
                            {"name": "P4", "color": "blue"},
                            {"name": "P5", "color": "gray"},
                        ],
                    },
                },
                "Due Date": {"date": {}},
                "Owner": {"rich_text": {}},
                "Source": {
                    "select": {
                        "options": [
                            {"name": "slack", "color": "purple"},
                            {"name": "outlook", "color": "blue"},
                            {"name": "teams", "color": "blue"},
                            {"name": "fathom", "color": "orange"},
                            {"name": "notion", "color": "gray"},
                            {"name": "unknown", "color": "default"},
                        ],
                    },
                },
                "Detected": {"date": {}},
            },
        })

    async def _create_briefings_db(
        self, client: httpx.AsyncClient, headers: Dict[str, str], parent_id: str,
    ) -> Dict[str, Any]:
        return await self._api_call(client, headers, "POST", NOTION_API_BASE + "/databases", {
            "parent": {"type": "page_id", "page_id": parent_id},
            "icon": {"type": "emoji", "emoji": "\U0001f4f0"},
            "title": [{"text": {"content": "Daily Briefings"}}],
            "properties": {
                "Name": {"title": {}},
                "Date": {"date": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Draft", "color": "yellow"},
                            {"name": "Published", "color": "green"},
                        ],
                    },
                },
            },
        })

    async def _create_meeting_prep_db(
        self, client: httpx.AsyncClient, headers: Dict[str, str], parent_id: str,
    ) -> Dict[str, Any]:
        return await self._api_call(client, headers, "POST", NOTION_API_BASE + "/databases", {
            "parent": {"type": "page_id", "page_id": parent_id},
            "icon": {"type": "emoji", "emoji": "\U0001f91d"},
            "title": [{"text": {"content": "Meeting Prep"}}],
            "properties": {
                "Name": {"title": {}},
                "Date": {"date": {}},
                "Participants": {"multi_select": {"options": []}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Pending", "color": "yellow"},
                            {"name": "Prepared", "color": "blue"},
                            {"name": "Done", "color": "green"},
                        ],
                    },
                },
            },
        })

    # ── Rate limiting and HTTP helpers ─────────────────────────

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer " + self._token,
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def _rate_limit(self) -> None:
        """Enforce 3 requests per second using a sliding window."""
        now = time.monotonic()
        # Remove timestamps older than 1 second
        self._request_times = [t for t in self._request_times if now - t < 1.0]
        if len(self._request_times) >= _RATE_LIMIT:
            wait = 1.0 - (now - self._request_times[0])
            if wait > 0:
                await asyncio.sleep(wait)
        self._request_times.append(time.monotonic())

    async def _api_call(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a Notion API call with rate limiting and retry.

        Rate-limit retries (429) use a separate budget from error retries.
        """
        last_error: Optional[Exception] = None
        rate_retries = 0

        attempt = 0
        while attempt < MAX_RETRIES:
            await self._rate_limit()
            try:
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=json_body or {})
                elif method == "PATCH":
                    resp = await client.patch(url, headers=headers, json=json_body or {})
                else:
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 429:
                    rate_retries += 1
                    if rate_retries > MAX_RATE_RETRIES:
                        raise RuntimeError("Notion rate limit exceeded after %d retries" % rate_retries)
                    retry_after = float(
                        resp.headers.get("Retry-After", BASE_DELAY * (2 ** rate_retries))
                    )
                    logger.warning(
                        "Notion rate limited (rate retry %d/%d), retrying in %.1fs",
                        rate_retries, MAX_RATE_RETRIES, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue  # Don't increment attempt

                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last_error = e
                attempt += 1
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Notion HTTP error (attempt %d/%d): %s, retrying in %.1fs",
                    attempt, MAX_RETRIES, str(e), delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Notion API call failed after retries")


def _map_status(status: str) -> str:
    """Map internal commitment status to Notion select option name."""
    mapping = {
        "pending": "Pending",
        "completed": "Completed",
        "cancelled": "Cancelled",
    }
    return mapping.get(status.lower(), "Pending")
