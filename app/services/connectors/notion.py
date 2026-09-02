"""Notion connector for pages and databases.

Uses the Notion API v1 (2022-06-28) to fetch pages and database items.
Rate-limited to 3 requests/second with retry on HTTP 429.
"""
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem
from app.services.notion.blocks import blocks_to_text, extract_rich_text

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT = 30.0
PAGE_SIZE = 100
MAX_PAGES = 100

MAX_RETRIES = 3
BASE_DELAY = 1.0

# Notion API rate limit: 3 requests per second
_RATE_LIMIT = 3


def _iso_timestamp(dt: datetime) -> str:
    """Format a datetime as ISO-8601 with UTC timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_title(page: Dict[str, Any]) -> str:
    """Extract the title from a Notion page or database object."""
    # Pages have properties with a "title" type
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return extract_rich_text(prop.get("title", []))

    # Databases have a top-level "title" field
    title_arr = page.get("title", [])
    if title_arr:
        return extract_rich_text(title_arr)

    return ""


def _extract_page_metadata(page: Dict[str, Any]) -> Dict[str, Any]:
    """Build metadata dict from a Notion page/database object."""
    obj_type = page.get("object", "page")
    parent = page.get("parent", {})
    parent_type = parent.get("type", "workspace")

    metadata: Dict[str, Any] = {
        "type": "notion_page" if obj_type == "page" else "notion_database_item",
        "title": _parse_title(page),
        "timestamp": page.get("last_edited_time", ""),
        "url": page.get("url", ""),
        "parent_type": parent_type,
    }

    # Extract last editor (fall back to id if name not available)
    last_edited_by = page.get("last_edited_by", {})
    metadata["author"] = last_edited_by.get("name", "") or last_edited_by.get("id", "")

    # Extract tags from a Tags/Labels multi_select property if present
    props = page.get("properties", {})
    for key in ("Tags", "tags", "Labels", "labels"):
        prop = props.get(key, {})
        if prop.get("type") == "multi_select":
            metadata["tags"] = [
                opt.get("name", "") for opt in prop.get("multi_select", [])
            ]
            break

    return metadata


class NotionConnector(BaseConnector):
    """Connector for Notion pages and databases."""

    @property
    def platform(self) -> str:
        return "notion"

    def __init__(self) -> None:
        # Token-bucket rate limiter: track timestamps of recent requests
        self._request_times: Deque[float] = deque()

    async def _rate_limit(self) -> None:
        """Enforce 3 requests per second using a sliding window."""
        loop = asyncio.get_event_loop()
        now = loop.time()

        # Remove timestamps older than 1 second
        while self._request_times and now - self._request_times[0] >= 1.0:
            self._request_times.popleft()

        # If we've hit the limit, wait until the oldest request expires
        if len(self._request_times) >= _RATE_LIMIT:
            wait = 1.0 - (now - self._request_times[0])
            if wait > 0:
                await asyncio.sleep(wait)

        self._request_times.append(asyncio.get_event_loop().time())

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
        **kwargs: Any,
    ) -> List[ConnectorItem]:
        """Fetch pages and database items modified since *since*."""
        items: List[ConnectorItem] = []
        headers = self._build_headers(access_token)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # Search for all pages and databases
            pages = await self._search_all(client, headers, since)

            for page in pages:
                obj_type = page.get("object", "page")

                if obj_type == "page":
                    item = await self._process_page(client, headers, page)
                    if item:
                        items.append(item)
                elif obj_type == "database":
                    db_items = await self._process_database(
                        client, headers, page, since,
                    )
                    items.extend(db_items)

        logger.info("Notion: fetched %d items", len(items))
        return items

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity by calling /users/me with retry."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                headers = self._build_headers(access_token)
                data = await self._api_call(
                    client, headers, "GET",
                    NOTION_API_BASE + "/users/me",
                )
                return bool(data.get("id"))
        except (httpx.HTTPError, RuntimeError):
            return False

    # ── Internal helpers ────────────────────────────────────────

    @staticmethod
    def _build_headers(token: str) -> Dict[str, str]:
        return {
            "Authorization": "Bearer " + token,
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def _api_call(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a Notion API call with rate limiting and retry on 429.

        Non-retryable status codes (401, 403, 404) raise immediately
        with a descriptive message so callers can handle them.
        """
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            await self._rate_limit()
            try:
                if method == "POST":
                    resp = await client.post(
                        url, headers=headers, json=json_body or {},
                    )
                else:
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 429:
                    retry_after = float(
                        resp.headers.get("Retry-After", BASE_DELAY * (2 ** attempt))
                    )
                    logger.warning(
                        "Notion rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # Non-retryable errors — raise immediately
                if resp.status_code == 401:
                    raise RuntimeError(
                        "Notion token is invalid or revoked. "
                        "Re-connect with /notion connect."
                    )
                if resp.status_code == 403:
                    raise RuntimeError(
                        "Notion integration lacks permission for this resource. "
                        "Check your Notion connection sharing settings."
                    )
                if resp.status_code == 404:
                    raise RuntimeError(
                        "Notion resource not found — it may have been deleted. "
                        "Run /notion workspace to reconfigure."
                    )

                resp.raise_for_status()
                return resp.json()
            except RuntimeError:
                raise
            except httpx.HTTPError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Notion HTTP error (attempt %d/%d): %s, retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, str(e), delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Notion API call failed after retries")

    async def _search_all(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Search the workspace for pages and databases, paginated.

        The Notion search endpoint does not support server-side filtering
        by ``last_edited_time``.  We sort descending and stop when we
        pass the *since* cutoff.
        """
        results: List[Dict[str, Any]] = []
        body: Dict[str, Any] = {
            "page_size": PAGE_SIZE,
            "sort": {
                "direction": "descending",
                "timestamp": "last_edited_time",
            },
        }

        for _ in range(MAX_PAGES):
            data = await self._api_call(
                client, headers, "POST",
                NOTION_API_BASE + "/search",
                json_body=body,
            )

            for item in data.get("results", []):
                # Client-side date filter
                if since:
                    edited_str = item.get("last_edited_time", "")
                    if edited_str:
                        edited = datetime.fromisoformat(
                            edited_str.replace("Z", "+00:00")
                        )
                        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
                        if edited < since_utc:
                            # Sorted descending — all remaining are older
                            return results
                results.append(item)

            if not data.get("has_more"):
                break
            body["start_cursor"] = data.get("next_cursor")

        return results

    async def _get_blocks(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        block_id: str,
        depth: int = 0,
        max_depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """Recursively retrieve child blocks of a block/page."""
        if depth >= max_depth:
            return []

        blocks: List[Dict[str, Any]] = []
        safe_id = quote(block_id, safe="")
        base_url = "%s/blocks/%s/children" % (NOTION_API_BASE, safe_id)

        start_cursor: Optional[str] = None
        for _ in range(MAX_PAGES):
            url = base_url
            params = "page_size=%d" % PAGE_SIZE
            if start_cursor:
                params += "&start_cursor=%s" % quote(start_cursor, safe="")
            url = base_url + "?" + params

            data = await self._api_call(client, headers, "GET", url)
            for block in data.get("results", []):
                if block.get("has_children"):
                    children = await self._get_blocks(
                        client, headers, block["id"],
                        depth=depth + 1, max_depth=max_depth,
                    )
                    block["children"] = children
                blocks.append(block)

            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor", "")

        return blocks

    async def _process_page(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        page: Dict[str, Any],
    ) -> Optional[ConnectorItem]:
        """Fetch block content for a page and return a ConnectorItem."""
        page_id = page.get("id", "")
        title = _parse_title(page)

        try:
            blocks = await self._get_blocks(client, headers, page_id)
        except (httpx.HTTPError, RuntimeError) as e:
            logger.warning("Failed to fetch blocks for page %s: %s", page_id, e)
            return None

        text = blocks_to_text(blocks)
        if not text.strip() and not title.strip():
            return None

        content = title + "\n\n" + text if title else text
        metadata = _extract_page_metadata(page)

        return ConnectorItem(
            content=content,
            source_id="notion:" + page_id,
            metadata=metadata,
        )

    async def _process_database(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        database: Dict[str, Any],
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Query a database and return ConnectorItems for its pages."""
        db_id = database.get("id", "")
        db_title = _parse_title(database)
        items: List[ConnectorItem] = []

        safe_db_id = quote(db_id, safe="")
        body: Dict[str, Any] = {"page_size": PAGE_SIZE}
        if since:
            body["filter"] = {
                "timestamp": "last_edited_time",
                "last_edited_time": {
                    "after": _iso_timestamp(since),
                },
            }

        for _ in range(MAX_PAGES):
            data = await self._api_call(
                client, headers, "POST",
                NOTION_API_BASE + "/databases/" + safe_db_id + "/query",
                json_body=body,
            )

            for page in data.get("results", []):
                item = await self._process_page(client, headers, page)
                if item:
                    # Enrich metadata with database name
                    item.metadata["database_name"] = db_title
                    item.metadata["type"] = "notion_database_item"
                    items.append(item)

            if not data.get("has_more"):
                break
            body["start_cursor"] = data.get("next_cursor")

        return items
