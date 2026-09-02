"""Slack connector supporting Bot Token and User Token.

Reads channels and DMs with cursor-based pagination.
For each channel, also fetches thread replies via conversations.replies.
Resolves user IDs to display names (cached per sync run).
Handles rate limiting (HTTP 429) with exponential backoff.

Token types and access scope:
  Bot Token  (xoxb-…)  Required scopes: channels:history, channels:read,
                        groups:history, groups:read, users:read
                        Access: channels and private channels the bot is a
                        member of. DMs (im/mpim) returned are the BOT's DMs,
                        not the user's personal conversations.

  User Token (xoxp-…)  Required scopes: channels:history, channels:read,
                        groups:history, groups:read, im:history, im:read,
                        mpim:history, mpim:read, users:read
                        Access: all channels and DMs visible to the
                        authenticated user, including personal DMs.

For full DM coverage, configure a User Token alongside the Bot Token:
  - access_token  → Bot Token  (used for channel messages)
  - user_token    → User Token (used for DMs: im + mpim)

If only a User Token is configured (access_token starts with xoxp-),
the connector uses it for everything (channels + DMs) automatically.
"""
import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

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

# Slack token prefixes
_BOT_TOKEN_PREFIX = "xoxb-"
_USER_TOKEN_PREFIX = "xoxp-"


def _is_user_token(token: str) -> bool:
    return token.startswith(_USER_TOKEN_PREFIX)


def _is_bot_token(token: str) -> bool:
    return token.startswith(_BOT_TOKEN_PREFIX)


class SlackConnector(BaseConnector):
    """Connector for Slack supporting Bot Token and User Token.

    Pass user_token to fetch_items to enable personal DM access.
    """

    @property
    def platform(self) -> str:
        return "slack"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
        user_token: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorItem]:
        """Fetch messages (including thread replies) from all accessible channels and DMs.

        Args:
            access_token: Bot Token (xoxb-) or User Token (xoxp-).
                          If a User Token is passed here, it is used for everything.
            since: Only fetch messages newer than this timestamp.
            user_token: Optional User Token (xoxp-) used exclusively for DM
                        fetching (im + mpim). When provided alongside a Bot Token
                        in access_token, Bot Token handles channel messages and
                        User Token handles DMs — giving full coverage.
        """
        # Determine effective tokens
        if _is_user_token(access_token):
            # Single User Token — use for everything
            channel_token = access_token
            dm_token: Optional[str] = access_token
            logger.info("Slack: using User Token for channels + DMs")
        else:
            # Bot Token for channels; User Token (if provided) for DMs
            channel_token = access_token
            dm_token = user_token
            if dm_token:
                logger.info("Slack: Bot Token for channels, User Token for DMs")
            else:
                logger.info(
                    "Slack: Bot Token only — personal DMs not accessible. "
                    "Configure a User Token (xoxp-) to enable DM sync."
                )

        items: List[ConnectorItem] = []

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            raw_messages: List[Dict[str, Any]] = []

            # 1. Fetch channel messages using channel_token
            channel_headers = {"Authorization": f"Bearer {channel_token}"}
            channel_types = "public_channel,private_channel"
            channels = await self._list_channels(client, channel_headers, channel_types)

            for channel in channels:
                channel_id = channel["id"]
                channel_name = channel.get("name", channel_id)
                try:
                    messages = await self._fetch_channel_history(
                        client, channel_headers, channel_id, since,
                    )
                except RuntimeError as e:
                    if "not_in_channel" in str(e):
                        logger.debug(
                            "Slack: skipping channel %s (bot not a member)", channel_name,
                        )
                        continue
                    raise

                for msg in messages:
                    msg["_channel_id"] = channel_id
                    msg["_channel_name"] = channel_name
                    raw_messages.append(msg)

                    # Fetch thread replies for thread parent messages
                    reply_count = msg.get("reply_count", 0) or 0
                    ts = msg.get("ts", "")
                    thread_ts = msg.get("thread_ts", "")
                    is_thread_parent = reply_count > 0 and (not thread_ts or thread_ts == ts)
                    if is_thread_parent:
                        replies = await self._fetch_thread_replies(
                            client, channel_headers, channel_id, ts, since,
                        )
                        for reply in replies:
                            if reply.get("ts") == ts:
                                continue  # skip the parent (already included)
                            reply["_channel_id"] = channel_id
                            reply["_channel_name"] = channel_name
                            raw_messages.append(reply)

            # 2. Fetch DMs and group DMs using dm_token (User Token only)
            if dm_token:
                dm_headers = {"Authorization": f"Bearer {dm_token}"}
                dm_channels = await self._list_channels(client, dm_headers, "im,mpim")

                for channel in dm_channels:
                    channel_id = channel["id"]
                    # DMs don't have a name; use the channel_type as label
                    channel_name = channel.get("name") or channel.get("user") or channel_id
                    try:
                        messages = await self._fetch_channel_history(
                            client, dm_headers, channel_id, since,
                        )
                    except RuntimeError as e:
                        logger.warning(
                            "Slack: skipping DM channel %s: %s", channel_id, e,
                        )
                        continue

                    for msg in messages:
                        msg["_channel_id"] = channel_id
                        msg["_channel_name"] = channel_name
                        msg["_is_dm"] = True
                        raw_messages.append(msg)

                        # Thread replies in DMs
                        reply_count = msg.get("reply_count", 0) or 0
                        ts = msg.get("ts", "")
                        thread_ts = msg.get("thread_ts", "")
                        is_thread_parent = reply_count > 0 and (not thread_ts or thread_ts == ts)
                        if is_thread_parent:
                            replies = await self._fetch_thread_replies(
                                client, dm_headers, channel_id, ts, since,
                            )
                            for reply in replies:
                                if reply.get("ts") == ts:
                                    continue
                                reply["_channel_id"] = channel_id
                                reply["_channel_name"] = channel_name
                                reply["_is_dm"] = True
                                raw_messages.append(reply)

            # 3. Resolve all user IDs to display names in one pass
            # Use channel_token for user resolution (bot token always has users:read)
            user_ids: Set[str] = set()
            for msg in raw_messages:
                uid = msg.get("user", "")
                if uid:
                    user_ids.add(uid)

            name_map = await self._resolve_usernames(client, channel_headers, user_ids)

            # 4. Build ConnectorItems
            for msg in raw_messages:
                text = msg.get("text", "")
                if not text or not text.strip():
                    continue

                uid = msg.get("user", "")
                author = name_map.get(uid, uid) if uid else ""
                channel_id = msg["_channel_id"]
                channel_name = msg["_channel_name"]
                ts = msg.get("ts", "")
                thread_ts = msg.get("thread_ts", "")
                is_dm = msg.get("_is_dm", False)

                items.append(ConnectorItem(
                    content=text,
                    source_id=f"{channel_id}:{ts}",
                    metadata={
                        "author": author,
                        "author_id": uid,
                        "channel": channel_name,
                        "channel_id": channel_id,
                        "timestamp": ts,
                        "type": "message",
                        "thread_ts": thread_ts,
                        "is_thread_reply": bool(thread_ts and thread_ts != ts),
                        "is_dm": is_dm,
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
                resp.raise_for_status()
                data = resp.json()
                return data.get("ok", False)
        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _list_channels(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        types: str,
    ) -> List[Dict[str, Any]]:
        """List channels of the given types with cursor pagination."""
        channels: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(MAX_PAGES):
            params: Dict[str, Any] = {
                "types": types,
                "limit": DEFAULT_PAGE_LIMIT,
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor

            data = await self._api_call(client, headers, "conversations.list", params)
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

            data = await self._api_call(client, headers, "conversations.history", params)
            messages.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return messages

    async def _fetch_thread_replies(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        channel_id: str,
        thread_ts: str,
        since: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch all replies in a thread via conversations.replies."""
        replies: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(MAX_PAGES):
            params: Dict[str, Any] = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": DEFAULT_PAGE_LIMIT,
            }
            if since:
                params["oldest"] = str(since.timestamp())
            if cursor:
                params["cursor"] = cursor

            try:
                data = await self._api_call(client, headers, "conversations.replies", params)
            except RuntimeError as e:
                logger.warning(
                    "Slack: could not fetch thread %s in %s: %s", thread_ts, channel_id, e,
                )
                break

            replies.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        return replies

    async def _resolve_usernames(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        user_ids: Set[str],
    ) -> Dict[str, str]:
        """Resolve a set of user IDs to display names.

        One users.info call per unique ID. Falls back to raw ID on error.
        """
        name_map: Dict[str, str] = {}
        for uid in user_ids:
            try:
                data = await self._api_call(
                    client, headers, "users.info", {"user": uid},
                )
                profile = data.get("user", {}).get("profile", {})
                name = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or uid
                )
                name_map[uid] = name
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                logger.warning("Slack: could not resolve user %s: %s", uid, e)
                name_map[uid] = uid

        return name_map

    async def _api_call(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        method: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make a Slack API call with rate limit retry and exponential backoff."""
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(
                    f"{SLACK_API_URL}/{method}",
                    headers=headers,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(
                        resp.headers.get("Retry-After", BASE_DELAY * (2 ** attempt))
                    )
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
