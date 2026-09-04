"""Domain-specific sub-agents for the multi-agent system.

Each agent covers one communication platform, runs its own agentic loop
with a filtered tool subset, and returns a structured analysis for the
orchestrator to synthesize.

All agents inherit BaseSubAgent; differences are:
  - system_prompt — platform-specific framing
  - tools         — schema subset from AGENT_TOOLS
  - _build_tool_executors — wires search_memory to the correct source filter
"""
import uuid
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.agents.base import BaseSubAgent
from app.services.agent.tool_definitions import (
    SLACK_TOOLS,
    OUTLOOK_TOOLS,
    TEAMS_TOOLS,
    FATHOM_TOOLS,
    NOTION_TOOLS,
)
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import LLMClient


class SlackAgent(BaseSubAgent):
    """Searches Slack messages and DMs for relevant context."""

    name: str = "slack"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Slack domain analyst for an AI Chief of Staff system. "
            "Your sole responsibility is to search Slack messages and DMs for information "
            "relevant to the user's query.\n\n"
            "Instructions:\n"
            "1. Call search_memory with source='slack' and a targeted query.\n"
            "2. If the first search is too broad or returns few results, try a more specific "
            "follow-up search with a different query term.\n"
            "3. Summarise what you found: relevant threads, decisions, commitments, and people "
            "mentioned in Slack that relate to the query.\n"
            "4. Be specific — include channel names, authors, and timestamps when available.\n"
            "5. If nothing relevant is found in Slack, state that explicitly.\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It is a structured "
            "analysis that will be combined with other domain analyses by the orchestrator. "
            "Keep it factual, attributed, and concise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return SLACK_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "search_memory": self._make_search_memory(
                db, user_id, default_source="slack"
            ),
        }


class OutlookAgent(BaseSubAgent):
    """Searches Outlook emails and calendar events for relevant context."""

    name: str = "outlook"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Outlook domain analyst for an AI Chief of Staff system. "
            "Your sole responsibility is to search emails and calendar events for information "
            "relevant to the user's query.\n\n"
            "Instructions:\n"
            "1. Call search_memory with source='outlook' to retrieve relevant emails.\n"
            "2. If the query mentions meetings, schedules, or upcoming events, also call "
            "get_calendar to check today's calendar.\n"
            "3. If the first search yields few results, try an alternative query.\n"
            "4. Summarise findings: key email threads, senders, dates, decisions, and any "
            "relevant calendar events.\n"
            "5. If nothing relevant is found in Outlook, state that explicitly.\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It is a structured "
            "analysis that will be combined with other domain analyses by the orchestrator. "
            "Keep it factual, attributed, and concise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return OUTLOOK_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "search_memory": self._make_search_memory(
                db, user_id, default_source="outlook"
            ),
            "get_calendar": self._make_get_calendar(db, user_id),
        }


class TeamsAgent(BaseSubAgent):
    """Searches Microsoft Teams chats for relevant context."""

    name: str = "teams"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Microsoft Teams domain analyst for an AI Chief of Staff system. "
            "Your sole responsibility is to search Teams chat messages for information "
            "relevant to the user's query.\n\n"
            "Instructions:\n"
            "1. Call search_memory with source='teams' and a targeted query.\n"
            "2. If the first search is too broad or returns few results, try a more specific "
            "follow-up search with a different query term.\n"
            "3. Summarise what you found: relevant conversations, decisions, action items, "
            "and people involved in Teams chats that relate to the query.\n"
            "4. Include the chat context (1:1 vs. group), authors, and timestamps when available.\n"
            "5. If nothing relevant is found in Teams, state that explicitly.\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It is a structured "
            "analysis that will be combined with other domain analyses by the orchestrator. "
            "Keep it factual, attributed, and concise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return TEAMS_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "search_memory": self._make_search_memory(
                db, user_id, default_source="teams"
            ),
        }


class FathomAgent(BaseSubAgent):
    """Searches Fathom meeting transcripts for relevant context.

    This agent is specially instructed to attribute statements to their
    speakers and distinguish commitments made BY the user from those
    assigned to others.
    """

    name: str = "fathom"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Fathom meeting-transcript domain analyst for an AI Chief of Staff system. "
            "Your sole responsibility is to search meeting transcripts for information "
            "relevant to the user's query.\n\n"
            "Critical transcript rules:\n"
            "- Transcripts contain what MULTIPLE speakers said during a meeting. "
            "Not every statement belongs to the user (Mariano).\n"
            "- Always attribute statements to their speaker. Never assume the user said something "
            "unless the transcript explicitly identifies them as the speaker.\n"
            "- Distinguish commitments made BY Mariano (he is responsible) from commitments "
            "assigned TO others (they are responsible, possibly mentioned in front of Mariano).\n"
            "- When ownership is ambiguous, flag it as unclear rather than assuming.\n\n"
            "Instructions:\n"
            "1. Call search_memory with source='fathom' and a targeted query.\n"
            "2. If the first search yields few results, try an alternative query (e.g. by "
            "meeting name, date range, or project name).\n"
            "3. For each relevant finding, state: meeting name/date, speaker, what was said, "
            "and whether any commitment was made — and by whom.\n"
            "4. If nothing relevant is found in Fathom transcripts, state that explicitly.\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It is a structured "
            "analysis that will be combined with other domain analyses by the orchestrator. "
            "Keep it factual, speaker-attributed, and concise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return FATHOM_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "search_memory": self._make_search_memory(
                db, user_id, default_source="fathom"
            ),
        }


class NotionAgent(BaseSubAgent):
    """Searches Notion pages and database items for relevant context."""

    name: str = "notion"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Notion domain analyst for an AI Chief of Staff system. "
            "Your sole responsibility is to search Notion pages and database items for "
            "information relevant to the user's query.\n\n"
            "Instructions:\n"
            "1. Call search_memory with source='notion' and a targeted query.\n"
            "2. If the first search is too broad or returns few results, try a more specific "
            "follow-up search (e.g. by page title, project name, or database property).\n"
            "3. Summarise what you found: relevant pages, database entries, decisions, and "
            "documentation that relates to the query.\n"
            "4. Include page titles, last-edited dates, and authors when available.\n"
            "5. If nothing relevant is found in Notion, state that explicitly.\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It is a structured "
            "analysis that will be combined with other domain analyses by the orchestrator. "
            "Keep it factual, attributed, and concise."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return NOTION_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "search_memory": self._make_search_memory(
                db, user_id, default_source="notion"
            ),
        }
