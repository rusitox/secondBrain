"""Strands tool wrappers for all secondBrain agent tools.

Exposes a factory function ``make_agent_tools`` that injects the DB session,
user_id, timezone, and embedder into each tool via closures, returning a list
of Strands-compatible tool objects ready for an Agent.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from strands import tool

__all__ = ["make_agent_tools"]

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_HTTP_RESPONSE_CHAR_LIMIT = 8000
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def make_agent_tools(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_timezone: str = "UTC",
    embedder: Optional[Any] = None,
) -> List[Any]:
    """Factory that creates all agent tools with db/user_id injected via closure.

    Args:
        db: Async SQLAlchemy session scoped to the current request.
        user_id: UUID of the authenticated user.
        user_timezone: IANA timezone name used for calendar localisation.
        embedder: Optional Embedder instance required by memory tools.

    Returns:
        List of Strands tool objects ready to pass to an Agent.
    """

    @tool
    async def search_memory(
        query: str,
        source: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the user's personal knowledge base using semantic similarity.

        Args:
            query: The natural-language search query.
            source: Optional platform filter — one of slack, outlook, teams, fathom, notion.
            top_k: Maximum number of results to return.
        """
        from app.services.agent.tools.memory_retriever import MemoryRetrieverTool

        if embedder is None:
            logger.warning("search_memory called without embedder — returning empty list")
            return []
        return await MemoryRetrieverTool(embedder).run(
            db, user_id, query=query, source=source, top_k=top_k
        )

    @tool
    async def list_tasks() -> List[Dict[str, Any]]:
        """List all pending commitments and action items for the user.
        """
        from app.services.agent.tools.task_manager import TaskManagerTool

        return await TaskManagerTool().list_pending(db, user_id)

    @tool
    async def get_calendar(
        date: Optional[str] = None,
        upcoming_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get the user's calendar events for a given date.

        Args:
            date: Target date in YYYY-MM-DD format. Defaults to today in UTC.
            upcoming_only: When True, exclude events that have already started.
        """
        from app.services.agent.tools.calendar_sync import CalendarSyncTool

        parsed_date: Optional[datetime] = None
        if date is not None:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        return await CalendarSyncTool().get_today_events(
            db,
            user_id,
            date=parsed_date,
            upcoming_only=upcoming_only,
            user_timezone=user_timezone,
        )

    @tool
    async def get_user_style() -> Dict[str, Any]:
        """Get the user's communication persona, tone guidelines, and heuristics.
        """
        from app.services.agent.tools.style_analyzer import StyleAnalyzerTool

        return await StyleAnalyzerTool().get_style(db, user_id)

    @tool
    async def search_learnings(
        query: str,
        entity_name: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the user's long-term distilled memory entries by semantic similarity.

        Args:
            query: The natural-language search query.
            entity_name: Optional entity name to filter results (e.g. a person or project).
            top_k: Maximum number of results to return.
        """
        from app.services.agent.tools.search_learnings import SearchLearningsTool

        if embedder is None:
            logger.warning("search_learnings called without embedder — returning empty list")
            return []
        return await SearchLearningsTool(embedder).run(
            db, user_id, query=query, entity_name=entity_name, top_k=top_k
        )

    @tool
    async def save_learning(
        content: str,
        importance: int = 3,
        source_type: str = "conversation",
        source_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a learning or insight to the user's long-term memory.

        Args:
            content: The learning or insight text to store.
            importance: Importance score from 1 (low) to 5 (high). Defaults to 3.
            source_type: Origin type of the learning (e.g. conversation, document).
            source_ref: Optional reference identifier for the source (e.g. a message ID).
        """
        from app.services.agent.tools.save_learning import SaveLearningTool

        if embedder is None:
            logger.warning("save_learning called without embedder — skipping")
            return {"saved": False, "reason": "no_embedder"}
        return await SaveLearningTool(embedder).run(
            db,
            user_id,
            content=content,
            importance=importance,
            source_type=source_type,
            source_ref=source_ref,
        )

    @tool
    async def get_sync_status() -> List[Dict[str, Any]]:
        """Get the last sync timestamp and status for each connected platform integration.
        """
        from app.services.agent.tools.sync_status import SyncStatusTool

        return await SyncStatusTool().get_status(db, user_id)

    @tool
    def get_current_datetime() -> str:
        """Get the current date and time in UTC ISO 8601 format.
        """
        return datetime.now(timezone.utc).isoformat()

    tools = [
        search_memory,
        list_tasks,
        get_calendar,
        get_user_style,
        search_learnings,
        save_learning,
        get_sync_status,
        get_current_datetime,
    ]

    from app.core.config import get_settings

    settings = get_settings()

    if settings.brave_search_api_key:
        @tool
        async def web_search(query: str, count: int = 5) -> List[Dict[str, str]]:
            """Search the public web using Brave Search. Use this for questions
            about current events, facts outside the user's personal knowledge
            base, or anything not covered by search_memory/search_learnings.

            Args:
                query: The search query.
                count: Number of results to return (1-10). Defaults to 5.
            """
            capped_count = max(1, min(count, 10))
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                    resp = await client.get(
                        _BRAVE_SEARCH_URL,
                        params={"q": query, "count": capped_count},
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": settings.brave_search_api_key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPError as e:
                logger.warning("web_search: request failed for query=%r: %s", query, e)
                return []

            results = data.get("web", {}).get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("description", ""),
                }
                for r in results[:capped_count]
            ]

        tools.append(web_search)

    allowed_domains = {
        d.strip().lower()
        for d in settings.http_request_allowed_domains.split(",")
        if d.strip()
    }
    if allowed_domains:
        @tool
        async def http_request(url: str) -> str:
            """Fetch the contents of a URL via HTTP GET. Only works for a
            pre-approved allowlist of domains configured by the operator —
            use this to look up a specific known page (e.g. documentation),
            not to browse arbitrary user-supplied links.

            Args:
                url: The full URL to fetch (must be http:// or https://).
            """
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https"):
                return f"Error: unsupported URL scheme {parsed.scheme!r}. Only http/https are allowed."
            if hostname not in allowed_domains:
                logger.warning("http_request: blocked disallowed domain=%r for url=%r", hostname, url)
                return f"Error: domain {hostname!r} is not in the allowed list."

            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("http_request: request failed for url=%r: %s", url, e)
                return f"Error: request failed — {e}"

            content_type = resp.headers.get("content-type", "")
            if not any(t in content_type for t in ("text/", "application/json", "application/xml")):
                return f"Error: unsupported content-type {content_type!r}."

            return resp.text[:_HTTP_RESPONSE_CHAR_LIMIT]

        tools.append(http_request)

    logger.info("make_agent_tools: created %d tools for user=%s", len(tools), user_id)
    return tools
