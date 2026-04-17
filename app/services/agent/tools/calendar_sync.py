"""Calendar sync tool — fetch today's calendar events from knowledge base."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


class CalendarSyncTool:
    """Retrieves calendar events from the user's ingested data."""

    name: str = "calendar_sync"
    description: str = (
        "Get the user's calendar events for today or a specific date range. "
        "Returns meeting subjects, times, organizers, and attendees."
    )

    async def get_today_events(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch calendar events for a given date from ingested documents.

        Looks for documents with source='outlook' and metadata.type='calendar_event'
        that match the target date. Filters metadata in Python for cross-DB
        compatibility (JSONB operators are PG-only).
        """
        target_date = date or datetime.now(timezone.utc)
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
            events.append({
                "subject": meta.get("subject", ""),
                "timestamp": timestamp,
                "organizer": meta.get("author", ""),
                "attendees": meta.get("attendees", []),
                "content": doc.content[:500],
            })

        logger.info("Calendar: found %d events for %s (user=%s)", len(events), date_str, user_id)
        return events
