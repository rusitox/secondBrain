"""Commitment detection using Claude to analyze text for promises and action items.

Analyzes ingested text and extracts structured commitment data
including owner, due date, and priority.
"""
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from anthropic import APIStatusError, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.services.llm.claude_client import ClaudeClient
from app.services.commitments.prompts import format_detection_prompt

logger = logging.getLogger(__name__)


@dataclass
class DetectedCommitment:
    """A commitment detected from text analysis."""

    commitment_text: str
    owner: str
    due_date: Optional[str]
    priority: int


class CommitmentDetector:
    """Detects commitments in text using Claude."""

    def __init__(self, claude_client: ClaudeClient) -> None:
        self._claude = claude_client

    async def detect(
        self,
        text: str,
        timestamp: str = "",
    ) -> List[DetectedCommitment]:
        """Analyze text and return detected commitments.

        Args:
            text: The text to analyze for commitments.
            timestamp: ISO-8601 timestamp of the original message.

        Returns:
            List of detected commitments.
        """
        if not text or not text.strip():
            return []

        if not timestamp:
            timestamp = datetime.utcnow().isoformat()

        prompt = format_detection_prompt(text, timestamp)

        try:
            response = await self._claude.generate(
                system_prompt="You are a commitment detection system. Return only valid JSON arrays.",
                user_message=prompt,
                temperature=0.1,
            )
        except (APIStatusError, RateLimitError, RuntimeError) as e:
            logger.error("Claude API error during commitment detection: %s", e)
            return []

        return self._parse_response(response)

    async def detect_and_store(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        document_id: uuid.UUID,
        text: str,
        timestamp: str = "",
    ) -> List[Commitment]:
        """Detect commitments and store them in the database.

        Args:
            db: Database session.
            user_id: Owner of the commitments.
            document_id: Source document ID.
            text: Text to analyze.
            timestamp: ISO-8601 timestamp of the original message.

        Returns:
            List of created Commitment model instances.
        """
        detected = await self.detect(text, timestamp)
        if not detected:
            return []

        commitments: List[Commitment] = []
        for det in detected:
            due_date = self._parse_due_date(det.due_date)
            priority = max(1, min(5, det.priority))

            commitment = Commitment(
                id=uuid.uuid4(),
                user_id=user_id,
                document_id=document_id,
                commitment_text=det.commitment_text[:500],
                owner=det.owner or "unknown",
                due_date=due_date,
                status=CommitmentStatus.PENDING,
                priority=priority,
            )
            db.add(commitment)
            commitments.append(commitment)

        await db.flush()
        logger.info(
            "Detected %d commitments from document %s for user %s",
            len(commitments), document_id, user_id,
        )
        return commitments

    def _parse_response(self, response: str) -> List[DetectedCommitment]:
        """Parse Claude's JSON response into DetectedCommitment objects."""
        response = response.strip()

        # Strip markdown code fences if present
        if response.startswith("```"):
            lines = response.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            response = "\n".join(lines)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            logger.warning("Failed to parse commitment detection response: %r", response[:200])
            return []

        if not isinstance(data, list):
            logger.warning("Expected JSON array, got %s", type(data).__name__)
            return []

        results: List[DetectedCommitment] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            commitment_text = item.get("commitment_text", "").strip()
            if not commitment_text:
                continue
            raw_priority = item.get("priority", 3)
            priority = raw_priority if isinstance(raw_priority, (int, float)) else 3
            results.append(DetectedCommitment(
                commitment_text=commitment_text,
                owner=item.get("owner", "unknown"),
                due_date=item.get("due_date"),
                priority=int(priority),
            ))

        return results

    @staticmethod
    def _parse_due_date(date_str: Optional[str]) -> Optional[datetime]:
        """Parse an ISO date string into a datetime, returning None on failure."""
        if not date_str:
            return None
        try:
            # Python 3.8 fromisoformat doesn't support Z suffix
            cleaned = date_str.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            logger.warning("Could not parse due date: %r", date_str)
            return None
