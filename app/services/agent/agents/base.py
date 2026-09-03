"""Base class for domain sub-agents in the multi-agent system.

Each sub-agent is responsible for a single domain (Slack, Outlook, etc.)
and runs its own agentic loop using a filtered tool subset and a
specialized system prompt. Results are aggregated by the orchestrator.
"""
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.tools.memory_retriever import MemoryRetrieverTool
from app.services.agent.tools.task_manager import TaskManagerTool
from app.services.agent.tools.calendar_sync import CalendarSyncTool
from app.services.agent.tools.save_learning import SaveLearningTool
from app.services.agent.tools.search_learnings import SearchLearningsTool
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import LLMClient, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    """Result returned by a domain sub-agent after its agentic loop completes."""

    agent_name: str
    analysis: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: Optional[str] = None


class BaseSubAgent:
    """Abstract base for all domain sub-agents.

    Subclasses must implement:
      - system_prompt (property) — specialised prompt for this domain
      - tools (property)         — Anthropic tool schema list (subset of AGENT_TOOLS)
      - _build_tool_executors()  — maps tool names to async callables
    """

    name: str = "base"

    def __init__(self, llm: LLMClient, embedder: Embedder) -> None:
        self._llm = llm
        self._embedder = embedder
        self._save_learning_tool = SaveLearningTool(embedder)
        self._search_learnings_tool = SearchLearningsTool(embedder)

    @property
    def system_prompt(self) -> str:
        raise NotImplementedError("Subclasses must define system_prompt")

    @property
    def tools(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Subclasses must define tools")

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        raise NotImplementedError("Subclasses must define _build_tool_executors")

    # ------------------------------------------------------------------
    # Shared tool factory methods — available to all subclasses
    # ------------------------------------------------------------------

    def _make_search_memory(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        default_source: Optional[str] = None,
    ) -> Callable:
        """Return an async search_memory callable, optionally pinned to one source."""
        embedder = self._embedder

        async def _search_memory(
            query: str,
            source: Optional[str] = default_source,
            top_k: int = 5,
        ) -> List[Dict[str, Any]]:
            tool = MemoryRetrieverTool(embedder)
            return await tool.run(db, user_id, query, source=source, top_k=top_k)

        return _search_memory

    def _make_list_tasks(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Callable:
        async def _list_tasks(
            include_overdue: bool = False,
        ) -> List[Dict[str, Any]]:
            return await TaskManagerTool().list_pending(db, user_id)

        return _list_tasks

    def _make_get_calendar(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Callable:
        async def _get_calendar() -> List[Dict[str, Any]]:
            return await CalendarSyncTool().get_today_events(db, user_id)

        return _get_calendar

    def _make_save_learning(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Callable:
        save_tool = self._save_learning_tool

        async def _save_learning(
            content: str,
            entities: Optional[List[Dict[str, str]]] = None,
            importance: int = 3,
        ) -> Dict[str, Any]:
            return await save_tool.run(
                db,
                user_id,
                content=content,
                entities=entities,
                importance=importance,
                source_type="sub_agent",
            )

        return _save_learning

    def _make_search_learnings(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Callable:
        search_tool = self._search_learnings_tool

        async def _search_learnings(
            query: str,
            entity_name: Optional[str] = None,
            top_k: int = 5,
        ) -> List[Dict[str, Any]]:
            return await search_tool.run(
                db,
                user_id,
                query=query,
                entity_name=entity_name,
                top_k=top_k,
            )

        return _search_learnings

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
    ) -> SubAgentResult:
        """Run this sub-agent's agentic loop and return its analysis.

        Any exception is caught and returned as SubAgentResult(error=...) so
        that a single failing sub-agent does not abort the orchestrator's
        asyncio.gather() call.
        """
        try:
            logger.info("SubAgent[%s] starting for user=%s", self.name, user_id)
            tool_executors = self._build_tool_executors(db, user_id)
            messages = [{"role": "user", "content": query}]

            result = await self._llm.generate_with_tools(
                messages=messages,
                tools=self.tools,
                tool_executors=tool_executors,
                system=self.system_prompt,
            )

            logger.info(
                "SubAgent[%s] finished: %d tool calls, %d iterations",
                self.name,
                len(result.tool_calls),
                result.iterations,
            )
            return SubAgentResult(
                agent_name=self.name,
                analysis=result.final_answer,
                tool_calls=result.tool_calls,
            )

        except Exception as exc:
            logger.exception("SubAgent[%s] failed: %s", self.name, exc)
            return SubAgentResult(
                agent_name=self.name,
                analysis="",
                error=str(exc),
            )
