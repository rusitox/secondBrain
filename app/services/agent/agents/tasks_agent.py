"""TasksAgent — manages pending commitments with active ownership verification.

This agent is deliberately cautious: it never presents detected tasks as
confirmed user responsibilities. Instead it:
  - Lists all pending tasks via list_tasks
  - Cross-checks each task against long-term memory (search_learnings) to see
    if the user has already confirmed or rejected it
  - Clearly separates CONFIRMED tasks from tasks that NEED CONFIRMATION
  - Formulates specific ownership questions for ambiguous tasks
  - Saves user confirmations as high-importance learnings
"""
import uuid
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.agents.base import BaseSubAgent
from app.services.agent.tool_definitions import TASKS_TOOLS
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import LLMClient


class TasksAgent(BaseSubAgent):
    """Lists and verifies pending commitments with active ownership checks."""

    name: str = "tasks"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Tasks domain analyst for an AI Chief of Staff system. "
            "Your role is to surface pending commitments accurately — which means you MUST "
            "distinguish between tasks the user has confirmed and tasks that were auto-detected "
            "from messages and have NOT yet been verified.\n\n"
            "Mandatory workflow — follow this order:\n"
            "1. Call list_tasks to retrieve all pending commitments.\n"
            "2. For EACH task returned, call search_learnings with the task text as the query "
            "to check whether the user has already confirmed or rejected this task.\n"
            "   - A confirmed task will have a learning with source_type='user_confirmation'.\n"
            "   - An unconfirmed task has no matching learning.\n"
            "3. Examine the 'source' field on each task:\n"
            "   - Tasks with source.platform set were auto-detected from messages. "
            "They need user confirmation.\n"
            "   - Tasks where owner is 'Mariano' or the user's name: flag them as high-priority "
            "for cross-platform context lookup (note this in output for the orchestrator).\n"
            "   - Tasks where owner is ambiguous or unknown: include a specific question about "
            "who actually owns this task.\n\n"
            "Ownership rules:\n"
            "- NEVER present auto-detected tasks as 'your pending items'. "
            "Present them as 'I found these items that need verification'.\n"
            "- When owner is unclear, write the specific question: "
            "'Is task X something you committed to, or was it assigned to [other party]?'\n\n"
            "Saving confirmations (when the user's query implies confirmation):\n"
            "- If the user's query confirms a specific task is theirs, call save_learning with:\n"
            "  content: 'User confirmed ownership of task: [task text]'\n"
            "  importance: 5\n"
            "  source_type hint: use 'user_confirmation' in the content so it can be found later\n\n"
            "Output format — use these exact section headers:\n"
            "  CONFIRMED TASKS — tasks the user has previously confirmed (with evidence)\n"
            "  NEEDS CONFIRMATION — auto-detected tasks awaiting user verification, "
            "with source provenance (platform, author, date)\n"
            "  OWNERSHIP QUESTIONS — specific questions for tasks with ambiguous owners\n"
            "  CROSS-KNOWLEDGE FLAGS — tasks where owner='Mariano' that the orchestrator "
            "should route to the CrossKnowledgeAgent for additional context\n\n"
            "IMPORTANT: Your output is NOT the final user-facing answer. It feeds into the "
            "orchestrator's synthesis. Be precise, conservative, and source every claim."
        )

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return TASKS_TOOLS

    def _build_tool_executors(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> Dict[str, Callable]:
        return {
            "list_tasks": self._make_list_tasks(db, user_id),
            "search_learnings": self._make_search_learnings(db, user_id),
            "save_learning": self._make_save_learning(db, user_id),
        }
