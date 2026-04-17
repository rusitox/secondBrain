"""Unit tests for daily briefing generation."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.briefing.generator import BriefingGenerator, BriefingResult
from app.services.briefing.prompts import format_briefing_context, BRIEFING_SYSTEM_PROMPT
from app.services.briefing.scheduler import BriefingScheduler


class TestBriefingResult:
    """Tests for BriefingResult dataclass."""

    def test_defaults(self) -> None:
        r = BriefingResult(generated_at="2025-03-10T07:00:00")
        assert r.agenda == []
        assert r.pending_commitments == []
        assert r.overdue_commitments == []
        assert r.contextual_alerts == []
        assert r.briefing_text == ""

    def test_to_dict(self) -> None:
        r = BriefingResult(
            agenda=[{"subject": "Standup"}],
            pending_commitments=[{"commitment_text": "Do X"}],
            contextual_alerts=["Alert 1"],
            briefing_text="Your day...",
            generated_at="2025-03-10T07:00:00",
        )
        d = r.to_dict()
        assert len(d["agenda"]) == 1
        assert d["briefing_text"] == "Your day..."


class TestFormatBriefingContext:
    """Tests for format_briefing_context."""

    def test_empty_data(self) -> None:
        result = format_briefing_context([], [], [], "2025-03-10")
        assert "2025-03-10" in result
        assert "No meetings scheduled" in result

    def test_with_events(self) -> None:
        events = [{"subject": "Standup", "timestamp": "09:00", "organizer": "alice", "attendees": ["bob"]}]
        result = format_briefing_context(events, [], [], "2025-03-10")
        assert "Standup" in result
        assert "alice" in result

    def test_with_overdue(self) -> None:
        overdue = [{"commitment_text": "Send report", "owner": "speaker", "priority": 2, "due_date": "2025-03-08"}]
        result = format_briefing_context([], [], overdue, "2025-03-10")
        assert "OVERDUE" in result
        assert "Send report" in result

    def test_with_pending(self) -> None:
        pending = [{"commitment_text": "Review PR", "owner": "unknown", "priority": 3}]
        result = format_briefing_context([], pending, [], "2025-03-10")
        assert "Review PR" in result

    def test_contextual_alerts(self) -> None:
        events = [{"subject": "Call with Bob", "attendees": ["bob@example.com"], "organizer": "", "timestamp": "10:00"}]
        pending = [{"commitment_text": "Send docs to Bob", "owner": "bob@example.com", "priority": 2}]
        result = format_briefing_context(events, pending, [], "2025-03-10")
        assert "Contextual Alerts" in result
        assert "bob@example.com" in result

    def test_no_contextual_alerts_when_no_match(self) -> None:
        events = [{"subject": "Team meeting", "attendees": ["alice@test.com"], "organizer": "", "timestamp": "10:00"}]
        pending = [{"commitment_text": "Report for Charlie", "owner": "charlie@test.com", "priority": 3}]
        result = format_briefing_context(events, pending, [], "2025-03-10")
        assert "Contextual Alerts" not in result


class TestBriefingSystemPrompt:
    def test_contains_sections(self) -> None:
        assert "Agenda" in BRIEFING_SYSTEM_PROMPT
        assert "Commitments" in BRIEFING_SYSTEM_PROMPT
        assert "Contextual Alerts" in BRIEFING_SYSTEM_PROMPT

    def test_contains_tone_rules(self) -> None:
        assert "concise" in BRIEFING_SYSTEM_PROMPT.lower()


class TestBriefingGenerator:
    """Tests for BriefingGenerator."""

    @pytest.mark.asyncio
    async def test_generate_empty_data(self) -> None:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(return_value="No events or tasks for today.")
        generator = BriefingGenerator(claude_client=mock_claude)

        mock_db = AsyncMock()
        # Mock the DB to return empty results
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await generator.generate(mock_db, uuid.uuid4())
        assert result.generated_at != ""
        assert isinstance(result.briefing_text, str)

    @pytest.mark.asyncio
    async def test_generate_fallback_on_claude_error(self) -> None:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(side_effect=RuntimeError("API down"))
        generator = BriefingGenerator(claude_client=mock_claude)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await generator.generate(mock_db, uuid.uuid4())
        assert "Daily Briefing" in result.briefing_text

    def test_find_contextual_alerts(self) -> None:
        generator = BriefingGenerator(claude_client=MagicMock())
        events = [{"attendees": ["bob@co.com"], "organizer": ""}]
        commitments = [{"owner": "bob@co.com", "commitment_text": "Send report"}]
        alerts = generator._find_contextual_alerts(events, commitments)
        assert len(alerts) == 1
        assert "bob@co.com" in alerts[0]
        assert "Send report" in alerts[0]

    def test_find_contextual_alerts_empty(self) -> None:
        generator = BriefingGenerator(claude_client=MagicMock())
        assert generator._find_contextual_alerts([], []) == []

    def test_fallback_briefing(self) -> None:
        result = BriefingResult(
            agenda=[{"subject": "Meeting"}],
            overdue_commitments=[{"text": "X"}],
            pending_commitments=[{"text": "Y"}, {"text": "Z"}],
            contextual_alerts=["Alert 1"],
            generated_at="now",
        )
        text = BriefingGenerator._fallback_briefing(result)
        assert "Meetings today:** 1" in text
        assert "Overdue items:** 1" in text
        assert "Pending commitments:** 2" in text
        assert "Alert 1" in text


class TestBriefingScheduler:
    """Tests for BriefingScheduler."""

    def test_is_available(self) -> None:
        scheduler = BriefingScheduler()
        # Should be True or False depending on APScheduler install
        assert isinstance(scheduler.is_available, bool)

    def test_start_shutdown(self) -> None:
        scheduler = BriefingScheduler()
        # Should not raise even without APScheduler
        if scheduler.is_available:
            scheduler.start()
            scheduler.shutdown()

    def test_schedule_without_apscheduler(self) -> None:
        scheduler = BriefingScheduler()
        if not scheduler.is_available:
            result = scheduler.schedule_briefing("test-job", lambda: None)
            assert result is False
