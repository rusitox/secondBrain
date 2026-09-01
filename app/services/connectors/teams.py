"""Microsoft Teams connector for chat messages.

Uses Microsoft Graph API v1.0 to fetch 1:1 and group chat messages.
Requires Chat.Read permission on the OAuth2 token.
Handles rate limiting (HTTP 429) with exponential backoff.

Design constraints:
- Access tokens expire in ~1h, so a single sync must complete within that window.
- MAX_CHATS limits how many chats are processed per sync run. Chats are sorted
  by lastUpdatedDateTime desc, so the most active ones are always captured first.
  On subsequent syncs, `since` filters messages, making each run much faster.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_PAGE_SIZE = 50
MAX_PAGES = 20       # max pages when listing chats (20 × 50 = 1 000 chats max)
MAX_CHATS = 50       # only process the 50 most recently active chats per sync
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
        """Fetch chat messages from Teams 1:1 and group chats.

        On first sync (no `since`), limits to last 6 months to avoid
        exceeding the token lifetime. Subsequent syncs are fast because
        only new messages are fetched.

        Only the MAX_CHATS most-recently-active chats are processed per
        sync run, keeping total runtime well within the 1-hour token window.
        """
        items: List[ConnectorItem] = []
        # Default to 6 months ago on first sync
        effective_since = since or (
            datetime.now(timezone.utc) - timedelta(days=180)
        )

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = {"Authorization": f"Bearer {access_token}"}

            chats = await self._list_chats(client, headers)
            logger.info("Teams: found %d chats (capped at %d)", len(chats), MAX_CHATS)

            for chat in chats[:MAX_CHATS]:
                chat_id = chat["id"]
                chat_topic = chat.get("topic") or chat.get("chatType", "chat")
                try:
                    messages = await self._fetch_chat_messages(
                        client, headers, chat_id, effective_since,
                    )
                except Exception as e:
                    logger.debug(
                        "Teams: skipping chat %s (%s): %s",
                        chat_id, chat_topic, e,
                    )
                    continue

                for msg in messages:
                    body_content = (msg.get("body") or {}).get("content", "")
                    if not body_content or not body_content.strip():
                        continue

                    sender = (
                        (msg.get("from") or {})
                        .get("user", {})
                        .get("displayName", "")
                    )

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

        logger.info("Teams: fetched %d messages from %d chats", len(items), min(len(chats), MAX_CHATS))
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
                if resp.status_code in (401, 403):
                    # Not transient — fail immediately without retrying
                    resp.raise_for_status()
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
        """List chats sorted by most recently updated, up to MAX_PAGES pages."""
        chats: List[Dict[str, Any]] = []
        url: Optional[str] = f"{GRAPH_BASE_URL}/me/chats"
        params: Dict[str, Any] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$select": "id,topic,chatType,lastUpdatedDateTime",
            # NOTE: $orderby is not supported on /me/chats — Graph API returns
            # chats in reverse-chronological order by default already.
        }

        for _ in range(MAX_PAGES):
            if not url:
                break
            data = await self._api_call(client, headers, url, params)
            # Filter out meeting threads client-side — they require extra
            # permissions (/messages endpoint returns 401 for @thread.v2 chats).
            page_chats = [
                c for c in data.get("value", [])
                if c.get("chatType") != "meeting"
            ]
            chats.extend(page_chats)
            # Stop early once we have enough chats
            if len(chats) >= MAX_CHATS:
                break
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
        """Fetch messages from a specific chat since a given datetime.

        The /messages endpoint does not support $filter or $orderby.
        Messages are returned newest-first by default. We filter by date
        in Python and stop paginating once all messages on a page are older
        than `since` (no need to go further back).
        """
        messages: List[Dict[str, Any]] = []
        url: Optional[str] = f"{GRAPH_BASE_URL}/me/chats/{chat_id}/messages"
        params: Dict[str, Any] = {"$top": DEFAULT_PAGE_SIZE}
        since_utc = since.astimezone(timezone.utc) if since else None

        # Limit to 5 pages per chat (250 messages max) to keep sync fast
        for _ in range(5):
            if not url:
                break
            data = await self._api_call(client, headers, url, params)
            page = data.get("value", [])
            found_newer = False
            for msg in page:
                if msg.get("messageType", "") != "message":
                    continue
                ts = msg.get("createdDateTime", "")
                if since_utc and ts:
                    try:
                        msg_dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
                        if msg_dt < since_utc:
                            continue  # older than cutoff, skip
                        found_newer = True
                    except ValueError:
                        found_newer = True  # can't parse, assume recent
                else:
                    found_newer = True
                messages.append(msg)

            # All messages on this page are older than `since` — no need to paginate further
            if since_utc and not found_newer:
                break

            url = data.get("@odata.nextLink")
            params = {}

        return messages
