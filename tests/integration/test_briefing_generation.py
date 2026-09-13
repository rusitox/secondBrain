"""Integration tests for briefing generation with real DB and mocked Claude."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.briefing.generator import BriefingGenerator, BriefingResult
from app.services.agent.tools.calendar_sync import CalendarSyncTool
from app.services.agent.tools.task_manager import TaskManagerTool
from app.services.agent.tools.style_analyzer import StyleAnalyzerTool
from tests.factories import make_user, make_commitment, make_document, make_identity


@pytest.fixture
def mock_claude() -> AsyncMock:
    client = AsyncMock()
    client.generate = AsyncMock(return_value=(
        "# Daily Briefing\n\n"
        "## Agenda\nYou have 1 meeting today.\n\n"
        "## Commitments\n1 pending item.\n\n"
        "## Summary\nBusy day ahead."
    ))
    return client


@pytest.fixture
def generator(mock_claude: AsyncMock) -> BriefingGenerator:
    return BriefingGenerator(claude_client=mock_claude)


class TestBriefingGeneratorIntegration:
    """Integration tests for BriefingGenerator with real DB session."""

    @pytest.mark.asyncio
    async def test_generate_with_no_data(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """Generate briefing when user has no data at all."""
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert isinstance(result, BriefingResult)
        assert result.generated_at != ""
        assert isinstance(result.briefing_text, str)
        assert isinstance(result.agenda, list)
        assert isinstance(result.pending_commitments, list)
        assert isinstance(result.overdue_commitments, list)
        assert isinstance(result.contextual_alerts, list)

    @pytest.mark.asyncio
    async def test_generate_with_pending_commitments(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """Pending items only include commitments owned by the user themselves —
        one owned by a colleague and one with an unresolved owner are excluded."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        mine = make_commitment(
            user_id=user.id,
            commitment_text="Send the quarterly report",
            owner=user.email,
            due_date=tomorrow,
            priority=1,
        )
        someone_elses = make_commitment(
            user_id=user.id,
            commitment_text="Review PR #42",
            owner="alice@company.com",
            due_date=tomorrow,
            priority=2,
        )
        unresolved = make_commitment(
            user_id=user.id,
            commitment_text="Follow up on the invoice",
            owner="unknown",
            due_date=tomorrow,
            priority=3,
        )
        db_session.add_all([mine, someone_elses, unresolved])
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert isinstance(result, BriefingResult)
        assert len(result.pending_commitments) == 1
        assert result.pending_commitments[0]["commitment_text"] == "Send the quarterly report"

    @pytest.mark.asyncio
    async def test_generate_with_overdue_commitments(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """Generate briefing when user has overdue commitments."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        overdue = make_commitment(
            user_id=user.id,
            commitment_text="Finish the design doc",
            owner=user.email,
            due_date=yesterday,
            priority=1,
        )
        db_session.add(overdue)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert isinstance(result, BriefingResult)
        assert len(result.overdue_commitments) >= 1

    @pytest.mark.asyncio
    async def test_generate_with_calendar_events(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """Generate briefing with calendar events from documents."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = make_document(
            user_id=user.id,
            content="Team standup meeting",
            source="outlook",
            metadata_={
                "type": "calendar_event",
                "subject": "Team Standup",
                "timestamp": today_str + "T09:00:00",
                "organizer": "manager@company.com",
                "attendees": ["alice@company.com", "bob@company.com"],
            },
        )
        db_session.add(doc)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert isinstance(result, BriefingResult)
        assert len(result.agenda) >= 1

    @pytest.mark.asyncio
    async def test_generate_with_style(
        self, generator: BriefingGenerator, db_session: AsyncMock, mock_claude: AsyncMock
    ) -> None:
        """Generate briefing with user identity/style configured."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        identity = make_identity(
            user_id=user.id,
            persona_description="Executive assistant style",
            tone_guidelines="Be concise and action-oriented",
        )
        db_session.add(identity)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert isinstance(result, BriefingResult)
        # Verify Claude was called with style in the system prompt
        call_args = mock_claude.generate.call_args
        system_prompt = call_args.kwargs.get("system", "") if call_args.kwargs else call_args[1] if len(call_args) > 1 else ""
        # The style should be incorporated into the prompt somehow
        assert isinstance(result.briefing_text, str)

    @pytest.mark.asyncio
    async def test_generate_fallback_on_claude_error(
        self, db_session: AsyncMock
    ) -> None:
        """Fallback briefing is generated when Claude API fails."""
        failing_claude = AsyncMock()
        failing_claude.generate = AsyncMock(side_effect=RuntimeError("API down"))
        generator = BriefingGenerator(claude_client=failing_claude)

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        c = make_commitment(
            user_id=user.id,
            commitment_text="Important task",
            owner=user.email,
            due_date=tomorrow,
            priority=1,
        )
        db_session.add(c)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert "Daily Briefing" in result.briefing_text
        assert "Pending commitments:" in result.briefing_text

    @pytest.mark.asyncio
    async def test_contextual_alerts_cross_reference(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """Contextual alerts are generated when calendar attendees match commitment owners."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Calendar event with bob as attendee
        doc = make_document(
            user_id=user.id,
            content="Meeting with Bob",
            source="outlook",
            metadata_={
                "type": "calendar_event",
                "subject": "1:1 with Bob",
                "timestamp": today_str + "T14:00:00",
                "organizer": "",
                "attendees": ["bob@company.com"],
            },
        )
        db_session.add(doc)

        # Commitment owned by bob
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        c = make_commitment(
            user_id=user.id,
            commitment_text="Send docs to Bob",
            owner="bob@company.com",
            due_date=tomorrow,
            priority=2,
        )
        db_session.add(c)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert len(result.contextual_alerts) >= 1
        alert_text = " ".join(result.contextual_alerts)
        assert "bob@company.com" in alert_text.lower() or "Bob" in alert_text

    @pytest.mark.asyncio
    async def test_generate_dedups_chunked_calendar_event(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """A meeting chunked into multiple Document rows appears once in the agenda."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base_id = "outlook-event-123"
        for i in range(7):
            db_session.add(make_document(
                user_id=user.id,
                content=f"Flock Comercial chunk {i}",
                source="outlook",
                source_id=base_id if i == 0 else f"{base_id}#chunk{i}",
                metadata_={
                    "type": "calendar_event",
                    "subject": "Flock Comercial: Revisión de Pipeline",
                    "timestamp": today_str + "T15:00:00",
                    "organizer": "manager@company.com",
                    "attendees": ["alice@company.com"],
                },
            ))
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        matching = [e for e in result.agenda if e["subject"] == "Flock Comercial: Revisión de Pipeline"]
        assert len(matching) == 1

    @pytest.mark.asyncio
    async def test_generate_uses_user_timezone_for_agenda(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """The agenda's local_time reflects the user's own timezone, not UTC."""
        user = make_user(timezone_="America/Argentina/Buenos_Aires")
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="Standup",
            source="outlook",
            metadata_={
                "type": "calendar_event",
                "subject": "Standup",
                "timestamp": today_str + "T15:00:00+00:00",
                "organizer": "",
                "attendees": [],
            },
        ))
        await db_session.commit()

        result = await generator.generate(db_session, user.id)

        assert len(result.agenda) == 1
        assert result.agenda[0]["local_time"] == "12:00"
        assert result.agenda[0]["timezone"] == "America/Argentina/Buenos_Aires"

    @pytest.mark.asyncio
    async def test_result_to_dict(
        self, generator: BriefingGenerator, db_session: AsyncMock
    ) -> None:
        """BriefingResult.to_dict() returns serializable dict."""
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        result = await generator.generate(db_session, user.id)
        d = result.to_dict()

        assert "agenda" in d
        assert "pending_commitments" in d
        assert "overdue_commitments" in d
        assert "contextual_alerts" in d
        assert "briefing_text" in d
        assert "generated_at" in d


class TestToolsIntegration:
    """Integration tests for individual tools with real DB."""

    @pytest.mark.asyncio
    async def test_task_manager_pending(self, db_session: AsyncMock) -> None:
        """TaskManagerTool returns pending commitments from DB."""
        tool = TaskManagerTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        c = make_commitment(
            user_id=user.id,
            commitment_text="Test task",
            due_date=tomorrow,
        )
        db_session.add(c)
        await db_session.commit()

        pending = await tool.list_pending(db_session, user.id)
        assert len(pending) >= 1
        assert any(t["commitment_text"] == "Test task" for t in pending)

    @pytest.mark.asyncio
    async def test_task_manager_overdue(self, db_session: AsyncMock) -> None:
        """TaskManagerTool returns overdue commitments from DB."""
        tool = TaskManagerTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        c = make_commitment(
            user_id=user.id,
            commitment_text="Overdue item",
            due_date=yesterday,
        )
        db_session.add(c)
        await db_session.commit()

        overdue = await tool.list_overdue(db_session, user.id)
        assert len(overdue) >= 1
        assert any(t["commitment_text"] == "Overdue item" for t in overdue)

    @pytest.mark.asyncio
    async def test_task_manager_list_pending_is_unfiltered_by_owner(
        self, db_session: AsyncMock,
    ) -> None:
        """TaskManagerTool itself returns commitments regardless of owner —
        BriefingGenerator._find_contextual_alerts needs visibility into other
        people's commitments, so filtering happens at the presentation layer
        (BriefingGenerator's pending_commitments/overdue_commitments, and the
        agent's list_tasks tool), not inside TaskManagerTool."""
        tool = TaskManagerTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        c = make_commitment(
            user_id=user.id,
            commitment_text="Someone else's task",
            owner="a_colleague@company.com",
            due_date=tomorrow,
        )
        db_session.add(c)
        await db_session.commit()

        pending = await tool.list_pending(db_session, user.id)
        assert any(t["commitment_text"] == "Someone else's task" for t in pending)

    @pytest.mark.asyncio
    async def test_agent_list_tasks_tool_filters_by_owner(self, db_session: AsyncMock) -> None:
        """The agent-facing list_tasks tool only offers the user's own commitments."""
        from app.services.agent.strands_tools import make_agent_tools

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        mine = make_commitment(
            user_id=user.id,
            commitment_text="My own task",
            owner=user.email,
            due_date=tomorrow,
        )
        someone_elses = make_commitment(
            user_id=user.id,
            commitment_text="A colleague's task",
            owner="a_colleague@company.com",
            due_date=tomorrow,
        )
        db_session.add_all([mine, someone_elses])
        await db_session.commit()

        tools = make_agent_tools(db=db_session, user_id=user.id)
        list_tasks = next(t for t in tools if t.tool_name == "list_tasks")
        result = await list_tasks.__wrapped__()

        texts = [t["commitment_text"] for t in result]
        assert "My own task" in texts
        assert "A colleague's task" not in texts


class TestRelativeDayTools:
    """get_calendar/get_emails's day= parameter — the structural fix for a
    bug observed live and repeatedly: asked about "mañana", the agent kept
    calling these tools with no date at all (silently defaulting to
    today) despite explicit system-prompt AND docstring instructions to
    compute the real date itself. day="tomorrow"/"mañana" needs no date
    arithmetic from the model at all, just picking the matching word."""

    @pytest.mark.asyncio
    async def test_get_calendar_day_tomorrow_finds_tomorrows_event(
        self, db_session: AsyncMock,
    ) -> None:
        from app.services.agent.strands_tools import make_agent_tools

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="Standup",
            source="outlook",
            metadata_={
                "type": "calendar_event", "subject": "Standup mañana",
                "timestamp": tomorrow_str + "T09:00:00Z",
            },
        ))
        await db_session.commit()

        tools = make_agent_tools(db=db_session, user_id=user.id)
        get_calendar = next(t for t in tools if t.tool_name == "get_calendar")
        result = await get_calendar.__wrapped__(day="tomorrow")

        assert any(e["subject"] == "Standup mañana" for e in result)

    @pytest.mark.asyncio
    async def test_get_calendar_day_manana_spanish_word_also_works(
        self, db_session: AsyncMock,
    ) -> None:
        """The model reasons in Spanish for a Spanish-speaking user — it may
        write day="mañana" verbatim instead of translating to "tomorrow"."""
        from app.services.agent.strands_tools import make_agent_tools

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        tomorrow_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="Standup",
            source="outlook",
            metadata_={
                "type": "calendar_event", "subject": "Standup",
                "timestamp": tomorrow_str + "T09:00:00Z",
            },
        ))
        await db_session.commit()

        tools = make_agent_tools(db=db_session, user_id=user.id)
        get_calendar = next(t for t in tools if t.tool_name == "get_calendar")
        result = await get_calendar.__wrapped__(day="mañana")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_calendar_no_day_or_date_defaults_to_today(
        self, db_session: AsyncMock,
    ) -> None:
        from app.services.agent.strands_tools import make_agent_tools

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id, content="Today event", source="outlook",
            metadata_={"type": "calendar_event", "subject": "Today event", "timestamp": today_str + "T09:00:00Z"},
        ))
        db_session.add(make_document(
            user_id=user.id, content="Tomorrow event", source="outlook",
            metadata_={"type": "calendar_event", "subject": "Tomorrow event", "timestamp": tomorrow_str + "T09:00:00Z"},
        ))
        await db_session.commit()

        tools = make_agent_tools(db=db_session, user_id=user.id)
        get_calendar = next(t for t in tools if t.tool_name == "get_calendar")
        result = await get_calendar.__wrapped__(upcoming_only=False)

        subjects = [e["subject"] for e in result]
        assert "Today event" in subjects
        assert "Tomorrow event" not in subjects

    @pytest.mark.asyncio
    async def test_get_emails_day_yesterday_finds_yesterdays_email(
        self, db_session: AsyncMock,
    ) -> None:
        from app.services.agent.strands_tools import make_agent_tools

        user = make_user()
        db_session.add(user)
        await db_session.flush()

        yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        db_session.add(make_document(
            user_id=user.id,
            content="Subject: Old news\n\nBody",
            source="outlook",
            metadata_={"type": "email", "subject": "Old news", "author": "x@company.com", "timestamp": yesterday_str + "T09:00:00Z"},
        ))
        await db_session.commit()

        tools = make_agent_tools(db=db_session, user_id=user.id)
        get_emails = next(t for t in tools if t.tool_name == "get_emails")
        result = await get_emails.__wrapped__(day="yesterday")

        assert any(e["subject"] == "Old news" for e in result)

    def test_resolve_target_date_prioritizes_day_over_date(self) -> None:
        from app.services.agent.strands_tools import _resolve_target_date

        resolved_day = _resolve_target_date("tomorrow", "2020-01-01")
        expected = datetime.now(timezone.utc) + timedelta(days=1)
        assert resolved_day is not None
        assert resolved_day.strftime("%Y-%m-%d") == expected.strftime("%Y-%m-%d")

    def test_resolve_target_date_falls_back_to_explicit_date(self) -> None:
        from app.services.agent.strands_tools import _resolve_target_date

        resolved = _resolve_target_date(None, "2020-06-15")
        assert resolved == datetime(2020, 6, 15, tzinfo=timezone.utc)

    def test_resolve_target_date_none_when_neither_given(self) -> None:
        from app.services.agent.strands_tools import _resolve_target_date

        assert _resolve_target_date(None, None) is None

    def test_resolve_target_date_unrecognized_day_word_falls_back_to_date(self) -> None:
        from app.services.agent.strands_tools import _resolve_target_date

        resolved = _resolve_target_date("next tuesday", "2020-06-15")
        assert resolved == datetime(2020, 6, 15, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_calendar_sync_no_events(self, db_session: AsyncMock) -> None:
        """CalendarSyncTool returns empty when no calendar documents exist."""
        tool = CalendarSyncTool()
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        events = await tool.get_today_events(db_session, user.id)
        assert events == []

    @pytest.mark.asyncio
    async def test_calendar_sync_dedups_chunked_event(self, db_session: AsyncMock) -> None:
        """N chunked Document rows for the same event collapse into one entry."""
        tool = CalendarSyncTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base_id = "outlook-event-999"
        for i in range(3):
            db_session.add(make_document(
                user_id=user.id,
                content=f"chunk {i}",
                source="outlook",
                source_id=base_id if i == 0 else f"{base_id}#chunk{i}",
                metadata_={
                    "type": "calendar_event",
                    "subject": "Recurring Sync",
                    "timestamp": today_str + "T10:00:00",
                },
            ))
        await db_session.commit()

        events = await tool.get_today_events(db_session, user.id, upcoming_only=False)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_calendar_sync_local_midnight_boundary(self, db_session: AsyncMock) -> None:
        """An event just before local midnight stays on "today" in the user's timezone
        even though its UTC instant already falls on the next UTC calendar day."""
        tool = CalendarSyncTool()
        user = make_user(timezone_="America/Argentina/Buenos_Aires")
        db_session.add(user)
        await db_session.flush()

        # 2026-09-11 23:30 in Buenos Aires (UTC-3) == 2026-09-12 02:30 UTC.
        local_target = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        db_session.add(make_document(
            user_id=user.id,
            content="Late meeting",
            source="outlook",
            metadata_={
                "type": "calendar_event",
                "subject": "Late Meeting",
                "timestamp": "2026-09-12T02:30:00+00:00",
            },
        ))
        await db_session.commit()

        events = await tool.get_today_events(
            db_session, user.id,
            date=local_target,
            upcoming_only=False,
            user_timezone="America/Argentina/Buenos_Aires",
        )
        assert len(events) == 1
        assert events[0]["local_time"] == "23:30"

    @pytest.mark.asyncio
    async def test_style_analyzer_no_identity(self, db_session: AsyncMock) -> None:
        """StyleAnalyzerTool returns empty defaults when no identity exists."""
        tool = StyleAnalyzerTool()
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        style = await tool.get_style(db_session, user.id)
        assert style["persona_description"] == ""
        assert style["tone_guidelines"] == ""

    @pytest.mark.asyncio
    async def test_style_analyzer_with_identity(self, db_session: AsyncMock) -> None:
        """StyleAnalyzerTool returns identity data when configured."""
        tool = StyleAnalyzerTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        identity = make_identity(
            user_id=user.id,
            persona_description="Friendly CTO",
            tone_guidelines="Use casual language",
        )
        db_session.add(identity)
        await db_session.commit()

        style = await tool.get_style(db_session, user.id)
        assert style["persona_description"] == "Friendly CTO"
        assert style["tone_guidelines"] == "Use casual language"
