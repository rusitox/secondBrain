"""Calendar sync tool — fetch today's calendar events from knowledge base."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


def _parse_event_timestamp(timestamp: str) -> Optional[datetime]:
    """Parse an ISO 8601 event timestamp into a timezone-aware datetime.

    Returns None if parsing fails so callers can fail-open (include the event).
    """
    if not timestamp:
        return None
    # Normalize 'Z' suffix — not supported by fromisoformat() in Python < 3.11
    normalized = timestamp.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        # If no tzinfo, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


class CalendarSyncTool:
    """Retrieves calendar events from the user's ingested data."""

    name: str = "calendar_sync"
    description: str = (
        "Get the user's upcoming calendar events for today. "
        "Returns meeting subjects, times, organizers, and attendees. "
        "Only returns events that have not yet started."
    )

    async def get_today_events(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        date: Optional[datetime] = None,
        upcoming_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch calendar events for a given date from ingested documents.

        Args:
            date: Target date (defaults to today UTC).
            upcoming_only: If True (default), exclude events that have already started.

        Looks for documents with source='outlook' and metadata.type='calendar_event'
        that match the target date. Filters metadata in Python for cross-DB
        compatibility (JSONB operators are PG-only).
        """
        now = datetime.now(timezone.utc)
        target_date = date or now
        date_str = target_date.strftime("%Y-%m-%d")

        # Query Outlook documents for this user, then filter calendar events in Python
        # (JSONB operators not supported on SQLite used in tests)
        stmt = (
            select(Document)
            .where(
                and_(
                    Document.user_id == user_id,
                    Document.source == "outlook",
                )
            )
        )
        result = await db.execute(stmt)
        docs = result.scalars().all()

        events: List[Dict[str, Any]] = []
        for doc in docs:
            meta = doc.metadata_ or {}
            if meta.get("type") != "calendar_event":
                continue
            timestamp = meta.get("timestamp", "")
            if date_str not in timestamp:
                continue

            if upcoming_only:
                event_dt = _parse_event_timestamp(timestamp)
                # Skip events that have already started; fail-open if unparseable
                if event_dt is not None and event_dt <= now:
                    continue

            events.append({
                "subject": meta.get("subject", ""),
                "timestamp": timestamp,
                "organizer": meta.get("author", ""),
                "attendees": meta.get("attendees", []),
                "content": doc.content[:500],
            })

        logger.info(
            "Calendar: found %d %s events for %s (user=%s)",
            len(events),
            "upcoming" if upcoming_only else "total",
            date_str,
            user_id,
        )
        return events
