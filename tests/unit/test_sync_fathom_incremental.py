"""Unit tests for scripts/sync_fathom_incremental.py.

Tests cover check_mode() and ingest_mode() with DB and pipeline mocked.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the module under test (functions, not __main__ block)
import importlib
import sys
import pathlib

# Ensure repo root is on sys.path
_REPO_ROOT = str(pathlib.Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.sync_fathom_incremental import check_mode, ingest_mode, USER_ID, PLATFORM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_integration(
    last_sync_at: Optional[datetime] = None,
) -> MagicMock:
    mock = MagicMock()
    mock.last_sync_at = last_sync_at
    mock.last_sync_status = None
    mock.last_sync_error = None
    return mock


def _make_db_session(integration: Optional[MagicMock]) -> AsyncMock:
    """Return a mock async session that returns *integration* on execute()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = integration

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# ---------------------------------------------------------------------------
# check_mode
# ---------------------------------------------------------------------------

class TestCheckMode:
    @pytest.mark.asyncio
    async def test_no_integration_prints_no_integration(self, capsys: pytest.CaptureFixture) -> None:
        """NO_INTEGRATION is printed when no Fathom integration row exists."""
        mock_session = _make_db_session(integration=None)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory):
            await check_mode()

        captured = capsys.readouterr()
        assert captured.out.strip() == "NO_INTEGRATION"

    @pytest.mark.asyncio
    async def test_never_synced_prints_never(self, capsys: pytest.CaptureFixture) -> None:
        """NEVER is printed when integration exists but last_sync_at is None."""
        integ = _make_integration(last_sync_at=None)
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory):
            await check_mode()

        captured = capsys.readouterr()
        assert captured.out.strip() == "NEVER"

    @pytest.mark.asyncio
    async def test_aware_datetime_prints_iso(self, capsys: pytest.CaptureFixture) -> None:
        """Timezone-aware last_sync_at is printed in ISO 8601 UTC format."""
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        integ = _make_integration(last_sync_at=dt)
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory):
            await check_mode()

        captured = capsys.readouterr()
        assert captured.out.strip() == "2026-01-15T10:30:00Z"

    @pytest.mark.asyncio
    async def test_naive_datetime_treated_as_utc(self, capsys: pytest.CaptureFixture) -> None:
        """Naive last_sync_at is treated as UTC (no tzinfo assumed)."""
        dt = datetime(2026, 3, 5, 8, 0, 0)  # naive
        integ = _make_integration(last_sync_at=dt)
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory):
            await check_mode()

        captured = capsys.readouterr()
        assert captured.out.strip() == "2026-03-05T08:00:00Z"


# ---------------------------------------------------------------------------
# ingest_mode — happy path
# ---------------------------------------------------------------------------

class TestIngestModeHappyPath:
    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self, capsys: pytest.CaptureFixture) -> None:
        """Empty meetings list prints a message and does not touch the DB."""
        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory):
            await ingest_mode([])

        captured = capsys.readouterr()
        assert "no meetings" in captured.out.lower()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_meeting_ingested(self, capsys: pytest.CaptureFixture) -> None:
        """A single valid meeting is ingested and last_sync_at is advanced."""
        meetings: List[Dict[str, Any]] = [
            {
                "source_id": "call-001",
                "title": "Q4 Review",
                "date": "2026-01-20T10:00:00",
                "content": "We discussed Q4 results.",
            }
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_result = MagicMock()
        mock_result.documents_created = 1
        mock_result.documents_updated = 0
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        mock_pipeline.ingest_raw.assert_called_once()
        mock_session.commit.assert_called_once()
        # last_sync_at must be updated
        assert integ.last_sync_at is not None
        assert integ.last_sync_status == "success"
        assert integ.last_sync_error is None

    @pytest.mark.asyncio
    async def test_last_sync_at_advances_to_max_date(self) -> None:
        """last_sync_at is set to the LATEST successfully ingested meeting date."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "a", "title": "Early", "date": "2026-01-01T00:00:00", "content": "x"},
            {"source_id": "b", "title": "Late", "date": "2026-06-01T00:00:00", "content": "y"},
            {"source_id": "c", "title": "Mid", "date": "2026-03-15T00:00:00", "content": "z"},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_result = MagicMock()
        mock_result.documents_created = 1
        mock_result.documents_updated = 0
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        expected_max = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert integ.last_sync_at == expected_max

    @pytest.mark.asyncio
    async def test_commitment_detector_wired_when_api_key_set(self) -> None:
        """CommitmentDetector is instantiated when llm_api_key is available."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "x1", "title": "T", "date": "2026-01-01T00:00:00", "content": "hey"},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_result = MagicMock()
        mock_result.documents_created = 0
        mock_result.documents_updated = 0
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = "sk-llm"
        mock_settings.llm_model = "claude-sonnet-4-6"

        mock_detector = MagicMock()
        mock_client = MagicMock()

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline) as MockPipeline, \
             patch("scripts.sync_fathom_incremental.Embedder"), \
             patch("app.services.llm.claude_client.ClaudeClient", return_value=mock_client), \
             patch("app.services.commitments.detector.CommitmentDetector", return_value=mock_detector):
            await ingest_mode(meetings)

        # IngestionPipeline must receive a commitment_detector kwarg
        call_kwargs = MockPipeline.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert "commitment_detector" in kw


# ---------------------------------------------------------------------------
# ingest_mode — error handling
# ---------------------------------------------------------------------------

class TestIngestModeErrors:
    @pytest.mark.asyncio
    async def test_missing_source_id_skipped(self, capsys: pytest.CaptureFixture) -> None:
        """Meetings without source_id are skipped without crashing."""
        meetings: List[Dict[str, Any]] = [
            {"title": "No ID", "date": "2026-01-01", "content": "stuff"},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock()

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        mock_pipeline.ingest_raw.assert_not_called()
        # last_sync_at must NOT be advanced when nothing succeeded
        assert integ.last_sync_at is None
        assert integ.last_sync_status == "error"

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self, capsys: pytest.CaptureFixture) -> None:
        """Meetings with no content are skipped without error."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "s1", "title": "Empty", "date": "2026-01-10", "content": ""},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock()

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        mock_pipeline.ingest_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_failure_advances_cursor_only_to_success(self) -> None:
        """last_sync_at advances only to the latest SUCCESSFUL meeting date."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "ok", "title": "OK", "date": "2026-02-01T00:00:00", "content": "a"},
            {"source_id": "bad", "title": "Bad", "date": "2026-05-01T00:00:00", "content": "b"},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        ok_result = MagicMock()
        ok_result.documents_created = 1
        ok_result.documents_updated = 0

        async def _fake_ingest_raw(**kwargs: Any) -> MagicMock:
            sid = kwargs.get("source_id") or ""
            if sid == "bad":
                raise RuntimeError("pipeline exploded")
            return ok_result

        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(side_effect=_fake_ingest_raw)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        # Cursor must stop at the successful meeting, not the later failing one
        expected = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert integ.last_sync_at == expected
        assert integ.last_sync_status == "error"
        assert "bad" in (integ.last_sync_error or "")

    @pytest.mark.asyncio
    async def test_all_fail_cursor_not_advanced(self) -> None:
        """If every meeting fails, last_sync_at is NOT changed."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "x", "title": "X", "date": "2026-08-01T00:00:00", "content": "c"},
        ]

        original_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        integ = _make_integration(last_sync_at=original_dt)
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(side_effect=RuntimeError("always fails"))

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        # last_sync_at must remain unchanged
        assert integ.last_sync_at == original_dt
        assert integ.last_sync_status == "error"

    @pytest.mark.asyncio
    async def test_unparseable_date_still_ingested(self) -> None:
        """A meeting with an unparseable date is ingested; cursor not advanced."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "m1", "title": "Bad date", "date": "not-a-date", "content": "transcript"},
        ]

        integ = _make_integration()
        mock_session = _make_db_session(integ)
        mock_factory = MagicMock(return_value=mock_session)

        ok_result = MagicMock()
        ok_result.documents_created = 1
        ok_result.documents_updated = 0
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(return_value=ok_result)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            await ingest_mode(meetings)

        mock_pipeline.ingest_raw.assert_called_once()
        # Cursor cannot advance (date was unparseable) but status is success
        assert integ.last_sync_at is None
        assert integ.last_sync_status == "success"

    @pytest.mark.asyncio
    async def test_no_integration_row_does_not_crash(self) -> None:
        """ingest_mode does not crash when there is no Fathom integration row."""
        meetings: List[Dict[str, Any]] = [
            {"source_id": "m1", "title": "T", "date": "2026-01-01T00:00:00", "content": "x"},
        ]

        # DB returns None for the integration
        mock_session = _make_db_session(integration=None)
        mock_factory = MagicMock(return_value=mock_session)

        ok_result = MagicMock()
        ok_result.documents_created = 1
        ok_result.documents_updated = 0
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_raw = AsyncMock(return_value=ok_result)

        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-test"
        mock_settings.llm_api_key = None

        with patch("scripts.sync_fathom_incremental.get_session_factory", return_value=mock_factory), \
             patch("scripts.sync_fathom_incremental.get_settings", return_value=mock_settings), \
             patch("scripts.sync_fathom_incremental.IngestionPipeline", return_value=mock_pipeline), \
             patch("scripts.sync_fathom_incremental.Embedder"):
            # Should not raise even without an integration row
            await ingest_mode(meetings)

        mock_pipeline.ingest_raw.assert_called_once()
        mock_session.commit.assert_called_once()
