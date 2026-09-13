"""Integration tests for EmailReaderTool — mirrors calendar_sync.py's
date-boundary tests, since search_memory alone can't answer "today's
emails" (see project memory: no notion of recency, let alone a specific
calendar day)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.tools.email_reader import EmailReaderTool
from tests.factories import make_document, make_user


class TestEmailReaderTool:
    @pytest.mark.asyncio
    async def test_no_emails_returns_empty(self, db_session: AsyncSession) -> None:
        tool = EmailReaderTool()
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        emails = await tool.get_emails_for_date(db_session, user.id)
        assert emails == []

    @pytest.mark.asyncio
    async def test_returns_todays_email(self, db_session: AsyncSession) -> None:
        tool = EmailReaderTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="Subject: Q3 numbers\n\nHere they are.",
            source="outlook",
            metadata_={
                "type": "email",
                "subject": "Q3 numbers",
                "author": "boss@company.com",
                "timestamp": today_str + "T09:00:00Z",
            },
        ))
        await db_session.commit()

        emails = await tool.get_emails_for_date(db_session, user.id)
        assert len(emails) == 1
        assert emails[0]["subject"] == "Q3 numbers"
        assert emails[0]["author"] == "boss@company.com"

    @pytest.mark.asyncio
    async def test_ignores_calendar_events_and_other_days(self, db_session: AsyncSession) -> None:
        tool = EmailReaderTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="standup",
            source="outlook",
            metadata_={"type": "calendar_event", "subject": "Standup", "timestamp": today_str + "T09:00:00Z"},
        ))
        db_session.add(make_document(
            user_id=user.id,
            content="old email",
            source="outlook",
            metadata_={"type": "email", "subject": "Old", "timestamp": "2020-01-01T09:00:00Z"},
        ))
        await db_session.commit()

        emails = await tool.get_emails_for_date(db_session, user.id)
        assert emails == []

    @pytest.mark.asyncio
    async def test_uses_user_timezone_for_local_time_and_day_boundary(
        self, db_session: AsyncSession,
    ) -> None:
        tool = EmailReaderTool()
        user = make_user(timezone_="America/Argentina/Buenos_Aires")
        db_session.add(user)
        await db_session.flush()

        # 2026-09-11 23:30 in Buenos Aires (UTC-3) == 2026-09-12 02:30 UTC.
        db_session.add(make_document(
            user_id=user.id,
            content="late email",
            source="outlook",
            metadata_={"type": "email", "subject": "Late", "timestamp": "2026-09-12T02:30:00+00:00"},
        ))
        await db_session.commit()

        target = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        emails = await tool.get_emails_for_date(
            db_session, user.id, date=target, user_timezone="America/Argentina/Buenos_Aires",
        )
        assert len(emails) == 1
        assert emails[0]["local_time"] == "23:30"
