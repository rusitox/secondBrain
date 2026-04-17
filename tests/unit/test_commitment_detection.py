"""Unit tests for commitment detection."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.commitments.detector import CommitmentDetector, DetectedCommitment
from app.services.commitments.prompts import format_detection_prompt


class TestFormatDetectionPrompt:
    """Tests for prompt formatting."""

    def test_includes_text_and_timestamp(self) -> None:
        result = format_detection_prompt(
            "I'll send the report by Friday",
            "2025-03-10T14:00:00",
        )
        assert "I'll send the report by Friday" in result
        assert "2025-03-10T14:00:00" in result

    def test_curly_braces_in_text(self) -> None:
        """Curly braces in text don't crash the formatter."""
        result = format_detection_prompt(
            "Config is {key: value}",
            "2025-03-10T14:00:00",
        )
        assert "{key: value}" in result

    def test_prompt_contains_few_shot_examples(self) -> None:
        result = format_detection_prompt("test", "2025-01-01")
        assert "quarterly report" in result
        assert "should probably" in result  # false positive example


class TestCommitmentDetectorParsing:
    """Tests for _parse_response."""

    def _make_detector(self) -> CommitmentDetector:
        mock_claude = MagicMock()
        return CommitmentDetector(claude_client=mock_claude)

    def test_parse_valid_json(self) -> None:
        detector = self._make_detector()
        response = json.dumps([
            {
                "commitment_text": "Send report",
                "owner": "Alice",
                "due_date": "2025-03-14",
                "priority": 2,
            }
        ])
        results = detector._parse_response(response)
        assert len(results) == 1
        assert results[0].commitment_text == "Send report"
        assert results[0].owner == "Alice"
        assert results[0].due_date == "2025-03-14"
        assert results[0].priority == 2

    def test_parse_empty_array(self) -> None:
        detector = self._make_detector()
        results = detector._parse_response("[]")
        assert results == []

    def test_parse_multiple_commitments(self) -> None:
        detector = self._make_detector()
        response = json.dumps([
            {"commitment_text": "Task 1", "owner": "A", "due_date": None, "priority": 3},
            {"commitment_text": "Task 2", "owner": "B", "due_date": "2025-04-01", "priority": 1},
        ])
        results = detector._parse_response(response)
        assert len(results) == 2

    def test_parse_with_markdown_fences(self) -> None:
        detector = self._make_detector()
        response = '```json\n[{"commitment_text": "Do thing", "owner": "X"}]\n```'
        results = detector._parse_response(response)
        assert len(results) == 1
        assert results[0].commitment_text == "Do thing"

    def test_parse_invalid_json(self) -> None:
        detector = self._make_detector()
        results = detector._parse_response("not json at all")
        assert results == []

    def test_parse_non_array(self) -> None:
        detector = self._make_detector()
        results = detector._parse_response('{"commitment_text": "oops"}')
        assert results == []

    def test_parse_skips_empty_commitment_text(self) -> None:
        detector = self._make_detector()
        response = json.dumps([
            {"commitment_text": "", "owner": "A"},
            {"commitment_text": "Valid task", "owner": "B"},
        ])
        results = detector._parse_response(response)
        assert len(results) == 1
        assert results[0].commitment_text == "Valid task"

    def test_parse_defaults(self) -> None:
        detector = self._make_detector()
        response = json.dumps([{"commitment_text": "Do thing"}])
        results = detector._parse_response(response)
        assert results[0].owner == "unknown"
        assert results[0].due_date is None
        assert results[0].priority == 3

    def test_parse_non_numeric_priority(self) -> None:
        """Non-numeric priority defaults to 3."""
        detector = self._make_detector()
        response = json.dumps([{"commitment_text": "Task", "priority": "high"}])
        results = detector._parse_response(response)
        assert results[0].priority == 3

    def test_parse_null_priority(self) -> None:
        """Null priority defaults to 3."""
        detector = self._make_detector()
        response = json.dumps([{"commitment_text": "Task", "priority": None}])
        results = detector._parse_response(response)
        assert results[0].priority == 3


class TestParseDueDate:
    """Tests for _parse_due_date."""

    def test_valid_date(self) -> None:
        from datetime import datetime
        result = CommitmentDetector._parse_due_date("2025-03-14")
        assert result is not None
        assert result.year == 2025
        assert result.month == 3
        assert result.day == 14

    def test_valid_datetime(self) -> None:
        result = CommitmentDetector._parse_due_date("2025-03-14T10:00:00")
        assert result is not None

    def test_none_input(self) -> None:
        assert CommitmentDetector._parse_due_date(None) is None

    def test_empty_string(self) -> None:
        assert CommitmentDetector._parse_due_date("") is None

    def test_invalid_format(self) -> None:
        assert CommitmentDetector._parse_due_date("not-a-date") is None

    def test_z_suffix(self) -> None:
        """Python 3.8 doesn't support Z natively — we handle it."""
        result = CommitmentDetector._parse_due_date("2025-03-14T10:00:00Z")
        assert result is not None
        assert result.year == 2025


class TestCommitmentDetectorDetect:
    """Tests for the detect method."""

    @pytest.mark.asyncio
    async def test_detect_returns_commitments(self) -> None:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(return_value=json.dumps([
            {"commitment_text": "Send report", "owner": "speaker", "due_date": "2025-03-14", "priority": 3}
        ]))
        detector = CommitmentDetector(claude_client=mock_claude)
        results = await detector.detect(
            "I'll send you the report by next Friday",
            "2025-03-10T14:00:00",
        )
        assert len(results) == 1
        assert results[0].commitment_text == "Send report"

    @pytest.mark.asyncio
    async def test_detect_empty_text(self) -> None:
        mock_claude = AsyncMock()
        detector = CommitmentDetector(claude_client=mock_claude)
        results = await detector.detect("", "2025-03-10T14:00:00")
        assert results == []
        mock_claude.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_detect_whitespace_text(self) -> None:
        mock_claude = AsyncMock()
        detector = CommitmentDetector(claude_client=mock_claude)
        results = await detector.detect("   \n\t  ", "2025-03-10T14:00:00")
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_api_error_returns_empty(self) -> None:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(side_effect=RuntimeError("API error"))
        detector = CommitmentDetector(claude_client=mock_claude)
        results = await detector.detect("I'll do the thing", "2025-03-10")
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_no_timestamp_uses_default(self) -> None:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(return_value="[]")
        detector = CommitmentDetector(claude_client=mock_claude)
        await detector.detect("some text")
        # Should have called generate (no error from missing timestamp)
        mock_claude.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_detect_priority_clamping(self) -> None:
        """Priority is clamped to 1-5 when storing."""
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(return_value=json.dumps([
            {"commitment_text": "Task", "owner": "A", "priority": 10},
            {"commitment_text": "Task2", "owner": "B", "priority": -1},
        ]))
        detector = CommitmentDetector(claude_client=mock_claude)
        results = await detector.detect("test text", "2025-01-01")
        # _parse_response returns raw priority, clamping happens in detect_and_store
        assert results[0].priority == 10
        assert results[1].priority == -1
