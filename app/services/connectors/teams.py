"""Microsoft Teams connector for chat messages.

Uses Microsoft Graph API v1.0 to fetch 1:1 and group chat messages.
Requires Chat.Read permission on the OAuth2 token.
Handles rate limiting (HTTP 429) with exponential backoff.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_PAGE_SIZE = 50
MAX_PAGES = 100
REQUEST_TIMEOUT = 30.0

MAX_RETRIES = 3
BASE_DELAY = 1.0


def _format_odata_datetime(dt: datetime) -> str:
    """Format datetime for OData $filter, ensuring UTC 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TeamsConnector(BaseConnector):
    """Connector for Microsoft Teams chat messages."""

    @property
    def platform(self) -> str:
        return "teams"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Fetch chat messages from Teams 1:1 and group chats."""
        items: List[ConnectorItem] = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = {"Authorization": f"Bearer {access_token}"}

            chats = await self._list_chats(client, headers)
            for chat in chats:
                chat_id = chat["id"]
                chat_topic = chat.get("topic") or chat.get("chatType", "chat")
                messages = await self._fetch_chat_messages(
                    client, headers, chat_id, since,
                )
                for msg in messages:
                    body_content = (
                        msg.get("body", {}).get("content", "")
                    )
                    if not body_content or not body_content.strip():
                        continue

                    sender = (
                        msg.get("from", {})
                        .get("user", {})
                        .get("displayName", "")
                    ) if msg.get("from") else ""

                    items.append(ConnectorItem(
                        content=body_content,
                        source_id=f"{chat_id}:{msg['id']}",
                        metadata={
                            "author": sender,
                            "chat_id": chat_id,
                            "chat_topic": chat_topic,
                            "chat_type": chat.get("chatType", ""),
                            "timestamp": msg.get("createdDateTime", ""),
                            "type": "teams_message",
                        },
                    ))

        logger.info("Teams: fetched %d messages", len(items))
        return items

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity against /me endpoint."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    f"{GRAPH_BASE_URL}/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _api_call(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make a Graph API call with rate limit retry and exponential backoff."""
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 429:
                    retry_after = float(
                        resp.headers.get("Retry-After", BASE_DELAY * (2 ** attempt))
                    )
                    logger.warning(
                        "Teams rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Teams HTTP error (attempt %d/%d): %s, retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, str(e), delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Teams API call failed after retries")

    async def _list_chats(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """List all chats the user is part of, with pagination."""
        chats: List[Dict[str, Any]] = []
        url: Optional[str] = f"{GRAPH_BASE_URL}/me/chats"
        params: Dict[str, Any] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$select": "id,topic,chatType,lastUpdatedDateTime",
        }

        for _ in range(MAX_PAGES):
            if not url:
                break
            data = await self._api_call(client, headers, url, params)
            chats.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = {}

        return chats

    async def _fetch_chat_messages(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        chat_id: str,
        since: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch messages from a specific chat, with pagination."""
        messages: List[Dict[str, Any]] = []
        url: Optional[str] = f"{GRAPH_BASE_URL}/me/chats/{chat_id}/messages"
        params: Dict[str, Any] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$orderby": "createdDateTime desc",
        }
        if since:
            params["$filter"] = (
                f"createdDateTime ge {_format_odata_datetime(since)}"
            )

        for _ in range(MAX_PAGES):
            if not url:
                break
            data = await self._api_call(client, headers, url, params)

            for msg in data.get("value", []):
                if msg.get("messageType", "") != "message":
                    continue
                messages.append(msg)

            url = data.get("@odata.nextLink")
            params = {}

        return messages
