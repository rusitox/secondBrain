"""Daily briefing generator.

Orchestrates calendar, commitments, and memory search
to produce a structured daily briefing via Claude.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.tools.calendar_sync import CalendarSyncTool
from app.services.agent.tools.task_manager import TaskManagerTool
from app.services.agent.tools.style_analyzer import StyleAnalyzerTool
from app.services.briefing.prompts import BRIEFING_SYSTEM_PROMPT, format_briefing_context
from anthropic import APIStatusError
from openai import APIError as OpenAIAPIError

from app.services.llm.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


@dataclass
class BriefingResult:
    """Result of a daily briefing generation."""

    agenda: List[Dict[str, Any]] = field(default_factory=list)
    pending_commitments: List[Dict[str, Any]] = field(default_factory=list)
    overdue_commitments: List[Dict[str, Any]] = field(default_factory=list)
    contextual_alerts: List[str] = field(default_factory=list)
    briefing_text: str = ""
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agenda": self.agenda,
            "pending_commitments": self.pending_commitments,
            "overdue_commitments": self.overdue_commitments,
            "contextual_alerts": self.contextual_alerts,
            "briefing_text": self.briefing_text,
            "generated_at": self.generated_at,
        }


class BriefingGenerator:
    """Generates daily briefings by orchestrating tools and Claude."""

    def __init__(self, claude_client: ClaudeClient) -> None:
        self._claude = claude_client
        self._calendar = CalendarSyncTool()
        self._tasks = TaskManagerTool()
        self._style = StyleAnalyzerTool()

    async def generate(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        target_date: Optional[datetime] = None,
    ) -> BriefingResult:
        """Generate a daily briefing for the user.

        Args:
            db: Database session.
            user_id: User to generate briefing for.
            target_date: Date for the briefing (defaults to today UTC).
        """
        now = target_date or datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        result = BriefingResult(generated_at=now.isoformat())

        # Step 1: Gather data from all tools
        result.agenda = await self._calendar.get_today_events(db, user_id, now, upcoming_only=False)
        result.pending_commitments = await self._tasks.list_pending(db, user_id)
        result.overdue_commitments = await self._tasks.list_overdue(db, user_id)

        # Step 2: Build contextual alerts
        result.contextual_alerts = self._find_contextual_alerts(
            result.agenda, result.pending_commitments + result.overdue_commitments
        )

        # Step 3: Get user style
        style = await self._style.get_style(db, user_id)
        style_context = ""
        if style.get("persona_description"):
            style_context = f"User persona: {style['persona_description']}"
        if style.get("tone_guidelines"):
            style_context += f"\nTone: {style['tone_guidelines']}"

        # Step 4: Generate briefing text via Claude
        context = format_briefing_context(
            events=result.agenda,
            pending=result.pending_commitments,
            overdue=result.overdue_commitments,
            date_str=date_str,
        )

        system = BRIEFING_SYSTEM_PROMPT
        if style_context:
            system = system + "\n\n" + style_context
        try:
            result.briefing_text = await self._claude.generate(
                system_prompt=system,
                user_message="Generate my daily briefing.\n\n" + context,
            )
        except (RuntimeError, ValueError, APIStatusError, OpenAIAPIError) as e:
            logger.error("Failed to generate briefing text: %s", e)
            result.briefing_text = self._fallback_briefing(result)

        logger.info("Generated briefing for user %s (date=%s)", user_id, date_str)
        return result

    def _find_contextual_alerts(
        self,
        events: List[Dict[str, Any]],
        commitments: List[Dict[str, Any]],
    ) -> List[str]:
        """Cross-reference calendar participants with commitment owners."""
        if not events or not commitments:
            return []

        # Collect all meeting participants
        participants: Dict[str, str] = {}  # lowercase -> original
        for event in events:
            for attendee in event.get("attendees", []):
                if attendee:
                    participants[attendee.lower()] = attendee
            org = event.get("organizer", "")
            if org:
                participants[org.lower()] = org

        alerts: List[str] = []
        for c in commitments:
            owner = c.get("owner", "").lower()
            if not owner or owner in ("unknown", "speaker"):
                continue
            for p_lower, p_original in participants.items():
                if owner in p_lower or p_lower in owner:
                    alerts.append(
                        f"You have a meeting with {p_original} — "
                        f"remember: {c.get('commitment_text', '')}"
                    )

        return alerts

    @staticmethod
    def _fallback_briefing(result: BriefingResult) -> str:
        """Generate a simple text briefing without Claude (fallback)."""
        lines = ["# Daily Briefing\n"]

        if result.agenda:
            lines.append(f"**Meetings today:** {len(result.agenda)}")
        else:
            lines.append("**No meetings scheduled.**")

        if result.overdue_commitments:
            lines.append(f"**Overdue items:** {len(result.overdue_commitments)}")
        if result.pending_commitments:
            lines.append(f"**Pending commitments:** {len(result.pending_commitments)}")

        if result.contextual_alerts:
            lines.append("\n**Alerts:**")
            for alert in result.contextual_alerts:
                lines.append(f"- {alert}")

        return "\n".join(lines)
