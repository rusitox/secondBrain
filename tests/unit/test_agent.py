"""Unit tests for agent orchestrator and tools."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.agent import AgentOrchestrator, AGENT_SYSTEM_PROMPT
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


class TestAgentOrchestrator:
    def _make_orchestrator(self) -> AgentOrchestrator:
        mock_claude = AsyncMock()
        mock_claude.generate = AsyncMock(return_value="Here's your answer.")
        mock_embedder = MagicMock()
        return AgentOrchestrator(claude_client=mock_claude, embedder=mock_embedder)

    @pytest.mark.asyncio
    async def test_query_basic(self) -> None:
        orch = self._make_orchestrator()
        mock_db = AsyncMock()
        # Mock all DB calls to return empty
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.agent.tools.memory_retriever.semantic_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            result = await orch.query(mock_db, uuid.uuid4(), "What's on my plate?")

        assert "answer" in result
        assert "tools_used" in result
        assert isinstance(result["sources"], list)

    @pytest.mark.asyncio
    async def test_query_with_calendar_keyword(self) -> None:
        orch = self._make_orchestrator()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.agent.tools.memory_retriever.semantic_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            result = await orch.query(mock_db, uuid.uuid4(), "What meetings do I have today?")

        # Calendar tool should be triggered by "meetings" and "today"
        assert isinstance(result["answer"], str)

    def test_format_style_with_data(self) -> None:
        orch = self._make_orchestrator()
        style = {"persona_description": "Executive", "tone_guidelines": "Be brief"}
        result = orch._format_style(style)
        assert "Executive" in result
        assert "Be brief" in result

    def test_format_style_empty(self) -> None:
        orch = self._make_orchestrator()
        assert orch._format_style({}) == ""

    def test_build_context_empty(self) -> None:
        orch = self._make_orchestrator()
        result = orch._build_context({})
        assert "No relevant context" in result

    def test_build_context_with_data(self) -> None:
        orch = self._make_orchestrator()
        tool_results = {
            "memory": [{"content": "Meeting notes", "source": "fathom", "metadata": {}}],
            "tasks": [{"commitment_text": "Send report", "owner": "Alice", "priority": 2, "due_date": "2025-03-14"}],
            "calendar": [{"subject": "Standup", "timestamp": "09:00", "attendees": ["bob"]}],
        }
        result = orch._build_context(tool_results)
        assert "Knowledge Base" in result
        assert "Meeting notes" in result
        assert "Pending Commitments" in result
        assert "Send report" in result
        assert "Calendar" in result
        assert "Standup" in result


class TestAgentSystemPrompt:
    def test_contains_capabilities(self) -> None:
        assert "knowledge base" in AGENT_SYSTEM_PROMPT
        assert "tasks" in AGENT_SYSTEM_PROMPT.lower()
        assert "calendar" in AGENT_SYSTEM_PROMPT.lower()

    def test_prompt_injection_protection(self) -> None:
        assert "untrusted" in AGENT_SYSTEM_PROMPT.lower()
