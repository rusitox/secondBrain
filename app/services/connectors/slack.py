"""Slack connector using Bot Token.

Reads channels and DMs with cursor-based pagination.
Handles rate limiting (HTTP 429) with exponential backoff.
"""
import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

SLACK_API_URL = "https://slack.com/api"
DEFAULT_PAGE_LIMIT = 200
MAX_PAGES = 100  # Safety limit to prevent infinite pagination loops
REQUEST_TIMEOUT = 30.0

# Rate limit retry
MAX_RETRIES = 3
BASE_DELAY = 1.0


class SlackConnector(BaseConnector):
    """Connector for Slack using Bot Token."""

    @property
    def platform(self) -> str:
        return "slack"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Fetch messages from all accessible channels and DMs."""
        items: List[ConnectorItem] = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = {"Authorization": f"Bearer {access_token}"}

            # Get list of channels the bot is in
            channels = await self._list_channels(client, headers)

            for channel in channels:
                channel_id = channel["id"]
                channel_name = channel.get("name", channel_id)
                try:
                    messages = await self._fetch_channel_history(
                        client, headers, channel_id, since,
                    )
                except RuntimeError as e:
                    if "not_in_channel" in str(e):
                        logger.debug("Slack: skipping channel %s (bot not a member)", channel_name)
                        continue
                    raise
                for msg in messages:
                    text = msg.get("text", "")
                    if not text or not text.strip():
                        continue  # skip empty messages (file-only, etc.)
                    items.append(ConnectorItem(
                        content=text,
                        source_id=f"{channel_id}:{msg['ts']}",
                        metadata={
                            "author": msg.get("user", ""),
                            "channel": channel_name,
                            "channel_id": channel_id,
                            "timestamp": msg.get("ts", ""),
                            "type": "message",
                            "thread_ts": msg.get("thread_ts", ""),
                        },
                    ))

        logger.info("Slack: fetched %d messages", len(items))
        return items

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity via auth.test."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    f"{SLACK_API_URL}/auth.test",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                data = resp.json()
                return data.get("ok", False)
        except httpx.HTTPError:
            return False

    async def _list_channels(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """List channels with cursor pagination."""
        channels: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(MAX_PAGES):
            params: Dict[str, Any] = {
                "types": "public_channel,private_channel,im,mpim",
                "limit": DEFAULT_PAGE_LIMIT,
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor

            data = await self._api_call(
                client, headers, "conversations.list", params,
            )

            channels.extend(data.get("channels", []))
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return channels

    async def _fetch_channel_history(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        channel_id: str,
        since: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch channel message history with cursor pagination."""
        messages: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(MAX_PAGES):
            params: Dict[str, Any] = {
                "channel": channel_id,
                "limit": DEFAULT_PAGE_LIMIT,
            }
            if since:
                params["oldest"] = str(since.timestamp())
            if cursor:
                params["cursor"] = cursor

            data = await self._api_call(
                client, headers, "conversations.history", params,
            )

            messages.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return messages

    async def _api_call(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        method: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make a Slack API call with rate limit retry."""
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(
                    f"{SLACK_API_URL}/{method}",
                    headers=headers,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", BASE_DELAY * (2 ** attempt)))
                    logger.warning(
                        "Slack rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok", False):
                    raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
                return data
            except httpx.HTTPError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Slack HTTP error (attempt %d/%d): %s, retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, str(e), delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Slack API call failed after retries")
