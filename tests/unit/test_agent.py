"""Unit tests for agent tools.

Orchestrator-level tests live in test_strands_orchestrator.py — the
orchestrator itself is StrandsOrchestrator (AgentOrchestrator/orchestrator.py
were removed in the Strands migration cleanup).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.tools.memory_retriever import MemoryRetrieverTool
from app.services.agent.tools.task_manager import TaskManagerTool
from app.services.agent.tools.calendar_sync import CalendarSyncTool
from app.services.agent.tools.style_analyzer import StyleAnalyzerTool


class TestMemoryRetrieverTool:
    def test_name_and_description(self) -> None:
        tool = MemoryRetrieverTool(embedder=MagicMock())
        assert tool.name == "memory_retriever"
        assert "knowledge base" in tool.description

    @pytest.mark.asyncio
    async def test_run_returns_results(self) -> None:
        mock_embedder = MagicMock()
        tool = MemoryRetrieverTool(embedder=mock_embedder)

        with patch("app.services.agent.tools.memory_retriever.semantic_search", new_callable=AsyncMock) as mock_search:
            from app.services.retrieval.search import SearchResult
            mock_search.return_value = [
                SearchResult(
                    document_id=uuid.uuid4(), content="test", source="slack",
                    source_id="s1", metadata={}, similarity=0.9,
                )
            ]
            results = await tool.run(AsyncMock(), uuid.uuid4(), "test query")
        assert len(results) == 1
        assert results[0]["source"] == "slack"


class TestTaskManagerTool:
    def test_name_and_description(self) -> None:
        tool = TaskManagerTool()
        assert tool.name == "task_manager"
        assert "commitments" in tool.description

    def test_commitment_to_dict(self) -> None:
        mock_c = MagicMock()
        mock_c.id = uuid.uuid4()
        mock_c.commitment_text = "Do X"
        mock_c.owner = "alice"
        mock_c.due_date = datetime(2025, 3, 14, tzinfo=timezone.utc)
        mock_c.status.value = "pending"
        mock_c.priority = 2
        d = TaskManagerTool._commitment_to_dict(mock_c)
        assert d["commitment_text"] == "Do X"
        assert d["owner"] == "alice"
        assert d["priority"] == 2


class TestCalendarSyncTool:
    def test_name_and_description(self) -> None:
        tool = CalendarSyncTool()
        assert tool.name == "calendar_sync"
        assert "calendar" in tool.description

    @pytest.mark.asyncio
    async def test_empty_db(self) -> None:
        tool = CalendarSyncTool()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        events = await tool.get_today_events(mock_db, uuid.uuid4())
        assert events == []


class TestStyleAnalyzerTool:
    def test_name_and_description(self) -> None:
        tool = StyleAnalyzerTool()
        assert tool.name == "style_analyzer"
        assert "style" in tool.description

    @pytest.mark.asyncio
    async def test_no_identity(self) -> None:
        tool = StyleAnalyzerTool()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        style = await tool.get_style(mock_db, uuid.uuid4())
        assert style["persona_description"] == ""
        assert style["tone_guidelines"] == ""

    @pytest.mark.asyncio
    async def test_with_identity(self) -> None:
        tool = StyleAnalyzerTool()
        mock_db = AsyncMock()
        mock_identity = MagicMock()
        mock_identity.persona_description = "Professional"
        mock_identity.tone_guidelines = "Be direct"
        mock_identity.heuristics = {"key": "value"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_identity
        mock_db.execute = AsyncMock(return_value=mock_result)
        style = await tool.get_style(mock_db, uuid.uuid4())
        assert style["persona_description"] == "Professional"
        assert style["heuristics"] == {"key": "value"}
