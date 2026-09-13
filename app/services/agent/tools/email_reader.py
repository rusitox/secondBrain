"""Email reader tool — fetch a given date's emails from the knowledge base.

Mirrors calendar_sync.py's date-boundary approach: pure semantic search
(memory_retriever.py) has no notion of "today" at all, so a question like
"what emails did I get today" needs an actual date filter, not a topic
similarity search.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dateutil import tz as dateutil_tz
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


def _parse_email_timestamp(timestamp: str) -> Optional[datetime]:
    """Parse an ISO 8601 email timestamp into a timezone-aware datetime.

    Returns None if parsing fails so callers can skip the email rather
    than guess which day it belongs to.
    """
    if not timestamp:
        return None
    normalized = timestamp.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _to_local_time(timestamp: str, user_timezone: str) -> Optional[str]:
    """Convert a UTC ISO timestamp to a local HH:MM string for the given timezone."""
    dt = _parse_email_timestamp(timestamp)
    if dt is None:
        return None
    local_tz = dateutil_tz.gettz(user_timezone) or dateutil_tz.UTC
    return dt.astimezone(local_tz).strftime("%H:%M")


class EmailReaderTool:
    """Retrieves emails from the user's ingested Outlook data, by date."""

    name: str = "email_reader"
    description: str = (
        "Get the user's emails for a given date. Returns subject, sender, "
        "local time received, and a content preview. Use this instead of "
        "search_memory for date-scoped questions like 'today's emails' — "
        "semantic search has no notion of 'today'."
    )

    async def get_emails_for_date(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        date: Optional[datetime] = None,
        user_timezone: str = "UTC",
    ) -> List[Dict[str, Any]]:
        """Fetch emails for a given date (defaults to today) in the user's timezone.

        Looks for documents with source='outlook' and metadata.type='email'
        whose receipt timestamp, converted to user_timezone, falls on the
        target date. The type filter runs in SQL on Postgres (JSONB
        ->> 'type') — this table can hold hundreds of thousands of a
        user's Outlook documents (calendar events included), and pulling
        all of them into Python just to keep the emails made this tool
        noticeably slow. SQLite (used in tests) has no JSONB operators, so
        it still filters in Python there, matching calendar_sync.py.
        """
        target_date = date or datetime.now(timezone.utc)
        local_tz = dateutil_tz.gettz(user_timezone) or dateutil_tz.UTC
        target_date_str = target_date.astimezone(local_tz).strftime("%Y-%m-%d")

        conditions = [Document.user_id == user_id, Document.source == "outlook"]
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            conditions.append(Document.metadata_["type"].astext == "email")
        stmt = select(Document).where(and_(*conditions))
        result = await db.execute(stmt)
        docs = result.scalars().all()

        emails: List[Dict[str, Any]] = []
        for doc in docs:
            meta = doc.metadata_ or {}
            if meta.get("type") != "email":
                continue
            timestamp = meta.get("timestamp", "")
            email_dt = _parse_email_timestamp(timestamp)
            if email_dt is None:
                continue
            if email_dt.astimezone(local_tz).strftime("%Y-%m-%d") != target_date_str:
                continue

            emails.append({
                "subject": meta.get("subject", ""),
                "author": meta.get("author", ""),
                "timestamp": timestamp,
                "local_time": _to_local_time(timestamp, user_timezone),
                "content": doc.content[:500],
            })

        logger.info(
            "Email reader: found %d emails for %s (user=%s)",
            len(emails), target_date_str, user_id,
        )
        return emails
