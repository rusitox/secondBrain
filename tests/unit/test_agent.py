"""Unit tests for agent orchestrator and tools."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.agent import AgentOrchestrator, AGENT_SYSTEM_PROMPT
from app.services.agent.tools.memory_retriever import MemoryRetrieverTool
from app.services.agent.tools.task_manager import TaskManagerTool
from app.services.agent.tools.calendar_sync import CalendarSyncTool
from app.services.agent.tools.style_analyzer import StyleAnalyzerTool
from app.services.llm.claude_client import ToolCall, ToolUseResult


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


def _make_empty_db():
    """Return a mock AsyncSession that returns empty query results."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _make_orchestrator(answer: str = "Here's your answer.") -> AgentOrchestrator:
    mock_llm = MagicMock()
    mock_llm.generate_with_tools = AsyncMock(return_value=ToolUseResult(
        final_answer=answer,
        tool_calls=[],
        iterations=1,
        stop_reason="end_turn",
    ))
    mock_embedder = MagicMock()
    return AgentOrchestrator(claude_client=mock_llm, embedder=mock_embedder)


class TestAgentOrchestrator:
    @pytest.mark.asyncio
    async def test_query_basic(self) -> None:
        """query() returns a dict with 'answer' key."""
        orch = _make_orchestrator("Here's your answer.")
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "What's on my plate?")
        assert "answer" in result
        assert result["answer"] == "Here's your answer."

    @pytest.mark.asyncio
    async def test_query_returns_session_id(self) -> None:
        """query() always returns a 'session_id' key."""
        orch = _make_orchestrator()
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "Hello?")
        assert "session_id" in result
        assert isinstance(result["session_id"], str)

    @pytest.mark.asyncio
    async def test_query_generates_session_id_when_none(self) -> None:
        """When session_id=None, a new UUID is generated and returned."""
        orch = _make_orchestrator()
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "Hello?", session_id=None)
        sid = result["session_id"]
        # Verify it's a valid UUID
        parsed = uuid.UUID(sid)
        assert str(parsed) == sid

    @pytest.mark.asyncio
    async def test_query_sources_from_search_memory(self) -> None:
        """When search_memory tool is used, its results appear in 'sources'."""
        doc = {"content": "Meeting notes", "source": "fathom", "metadata": {}}
        mock_llm = MagicMock()
        mock_llm.generate_with_tools = AsyncMock(return_value=ToolUseResult(
            final_answer="Found some notes.",
            tool_calls=[
                ToolCall(
                    tool_name="search_memory",
                    tool_input={"query": "meeting"},
                    tool_result=json.dumps([doc]),
                )
            ],
            iterations=2,
            stop_reason="end_turn",
        ))
        orch = AgentOrchestrator(claude_client=mock_llm, embedder=MagicMock())
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "Find my meeting notes")
        assert isinstance(result["sources"], list)
        assert len(result["sources"]) == 1
        assert result["sources"][0]["source"] == "fathom"

    @pytest.mark.asyncio
    async def test_query_tools_used_from_tool_calls(self) -> None:
        """tools_used list is built from the ToolCall records."""
        mock_llm = MagicMock()
        mock_llm.generate_with_tools = AsyncMock(return_value=ToolUseResult(
            final_answer="Done.",
            tool_calls=[
                ToolCall("get_user_style", {}, '{"persona": "exec"}'),
                ToolCall("list_tasks", {}, "[]"),
            ],
            iterations=3,
            stop_reason="end_turn",
        ))
        orch = AgentOrchestrator(claude_client=mock_llm, embedder=MagicMock())
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "What do I have today?")
        assert "get_user_style" in result["tools_used"]
        assert "list_tasks" in result["tools_used"]

    @pytest.mark.asyncio
    async def test_query_iterations_propagated(self) -> None:
        """iterations from ToolUseResult appears in the response."""
        mock_llm = MagicMock()
        mock_llm.generate_with_tools = AsyncMock(return_value=ToolUseResult(
            final_answer="Done.",
            tool_calls=[],
            iterations=5,
            stop_reason="end_turn",
        ))
        orch = AgentOrchestrator(claude_client=mock_llm, embedder=MagicMock())
        db = _make_empty_db()
        result = await orch.query(db, uuid.uuid4(), "test")
        assert result["iterations"] == 5

    @pytest.mark.asyncio
    async def test_session_id_echoed_when_provided(self) -> None:
        """When a valid session_id is provided with no history, it is echoed back."""
        orch = _make_orchestrator()
        db = _make_empty_db()
        provided_sid = str(uuid.uuid4())
        result = await orch.query(db, uuid.uuid4(), "Hello?", session_id=provided_sid)
        assert result["session_id"] == provided_sid


class TestAgentSystemPrompt:
    def test_contains_tool_names(self) -> None:
        assert "search_memory" in AGENT_SYSTEM_PROMPT
        assert "list_tasks" in AGENT_SYSTEM_PROMPT
        assert "get_calendar" in AGENT_SYSTEM_PROMPT
        assert "get_user_style" in AGENT_SYSTEM_PROMPT

    def test_prompt_injection_protection(self) -> None:
        assert "untrusted" in AGENT_SYSTEM_PROMPT.lower()

    def test_style_instruction_present(self) -> None:
        assert "get_user_style" in AGENT_SYSTEM_PROMPT
