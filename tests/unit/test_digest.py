"""Unit tests for weekly digest generator."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notion.digest import WeeklyDigestGenerator, DigestResult


class TestDigestResult:
    def test_to_dict(self) -> None:
        result = DigestResult(
            week_start="2026-04-13",
            week_end="2026-04-18",
            commitments_completed=3,
            commitments_new=2,
            commitments_overdue=1,
            commitments_pending=5,
            documents_processed=10,
            digest_text="# Digest",
            generated_at="2026-04-18T12:00:00+00:00",
        )
        d = result.to_dict()
        assert d["week_start"] == "2026-04-13"
        assert d["commitments_completed"] == 3
        assert d["documents_processed"] == 10
        assert d["digest_text"] == "# Digest"


class TestWeeklyDigestGenerator:
    def _make_generator(self) -> tuple:
        claude = MagicMock()
        claude.generate = AsyncMock(return_value="## Week in Review\nGreat week.")
        gen = WeeklyDigestGenerator(claude)
        return gen, claude

    @pytest.mark.asyncio
    async def test_generate_uses_claude(self) -> None:
        gen, claude = self._make_generator()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)

        db = AsyncMock()
        # Mock all DB queries to return 0
        scalar_mock = MagicMock(return_value=0)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalar.return_value = 0
        execute_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=execute_result)

        result = await gen.generate(
            db=db, user_id=user_id,
            week_start=week_start, week_end=now,
        )

        assert result.digest_text == "## Week in Review\nGreat week."
        claude.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_fallback_on_claude_error(self) -> None:
        gen, claude = self._make_generator()
        claude.generate = AsyncMock(side_effect=RuntimeError("Claude down"))
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)

        db = AsyncMock()
        scalar_mock = MagicMock(return_value=0)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalar.return_value = 0
        execute_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=execute_result)

        result = await gen.generate(
            db=db, user_id=user_id,
            week_start=week_start, week_end=now,
        )

        # Falls back to simple text
        assert "Weekly Digest" in result.digest_text
        assert "Completed:" in result.digest_text

    @pytest.mark.asyncio
    async def test_generate_defaults_to_last_monday(self) -> None:
        gen, claude = self._make_generator()
        user_id = uuid.uuid4()

        db = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalar.return_value = 0
        execute_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=execute_result)

        result = await gen.generate(db=db, user_id=user_id)

        # week_start should be a Monday
        ws = datetime.strptime(result.week_start, "%Y-%m-%d")
        assert ws.weekday() == 0  # Monday

    def test_build_context(self) -> None:
        result = DigestResult(
            week_start="2026-04-13",
            week_end="2026-04-18",
            commitments_completed=2,
            commitments_new=1,
            commitments_overdue=1,
            commitments_pending=3,
            documents_processed=5,
        )
        context = WeeklyDigestGenerator._build_context(result, [], [], [])
        assert "2026-04-13" in context
        assert "Commitments completed: 2" in context
        assert "Documents processed: 5" in context

    def test_fallback_digest(self) -> None:
        result = DigestResult(
            week_start="2026-04-13",
            week_end="2026-04-18",
            commitments_completed=2,
            commitments_new=1,
        )
        text = WeeklyDigestGenerator._fallback_digest(result)
        assert "Weekly Digest" in text
        assert "Completed: 2" in text
