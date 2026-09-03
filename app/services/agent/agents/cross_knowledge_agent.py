"""CrossKnowledgeAgent — finds patterns and connections across all platforms.

This agent does not filter by source. It is designed to:
  - Search the same topic across multiple platforms to surface connections
  - Recall prior ownership decisions from long-term memory (search_learnings)
  - Identify who appears across multiple channels around a topic
  - Save newly confirmed ownership insights for future recall
  - Surface a single clear ownership question when attribution is uncertain
"""
import uuid
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.agents.base import BaseSubAgent
from app.services.agent.tool_definitions import CROSS_KNOWLEDGE_TOOLS
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import LLMClient


class CrossKnowledgeAgent(BaseSubAgent):
    """Searches across all platforms to find cross-cutting patterns and connections."""

    name: str = "cross_knowledge"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Cross-Knowledge analyst for an AI Chief of Staff system. "
            "Your role is to find connections and patterns across ALL communication platforms "
            "(Slack, email, Teams, meeting transcripts, Notion) for the given topic.\n\n"
            "Mandatory workflow — follow this order:\n"
            "1. Call search_memory (no source filter) with the main query to get broad results.\n"
            "2. Call search_memory again with a DIFFERENT query angle (e.g. synonyms, related "
            "people, related project names) to surface results the first search missed.\n"
            "   You MUST make at least 2 search_memory calls with different queries.\n"
            "3. Call search_learnings to check whether prior ownership decisions or patterns "
            "have already been recorded about this topic.\n\n"
            "Cross-platform analysis — after searching:\n"
            "- Identify which platforms the topic appears on (e.g. 'mentioned in both email "
            "and Slack').\n"
            "- Identify the common thread: who is the key person, what is the recurring pattern, "
            "is there an evolution over time?\n"
            "- For items that appear to belong to Mariano: provide richer context — where was it "
            "first mentioned, who else is involved, what is the current status?\n"
            "- For items where ownership is uncertain: formulate ONE clear, specific question "
            "that the orchestrator can present to the user to resolve the ambiguity. "
            "Do not guess — flag it.\n\n"
            "Saving insights:\n"
            "- When you confirm ownership or a cross-platform pattern with high confidence "
            "(backed by at least 2 sources), call save_learning with importance=4.\n"
            "- Only save confirmed, non-trivial insights. Never save speculative conclusions.\n\n"
            "Output format:\n"
            "Provide a structured analysis with sections:\n"
            "  CROSS-PLATFORM FINDINGS — what appears across multiple sources\n"
            "  OWNERSHIP — confirmed owners, with evidence\n"
            "  PATTERNS — recurring themes or people\n"
            "  OPEN QUESTION — (only if ownership is uncertain) one clear question for the user\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It feeds into the "
            "orchestrator's synthesis. Be factual, cross-referenced, and precise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return CROSS_KNOWLEDGE_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        # search_memory without a default_source so the LLM can search all platforms
        return {
            "search_memory": self._make_search_memory(db, user_id),
            "search_learnings": self._make_search_learnings(db, user_id),
            "save_learning": self._make_save_learning(db, user_id),
        }
