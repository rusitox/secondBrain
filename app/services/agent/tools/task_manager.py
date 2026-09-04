"""Task manager tool — query and update commitments."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import CommitmentStatus
from app.services import commitment_service

logger = logging.getLogger(__name__)


class TaskManagerTool:
    """Manages the user's commitments and action items."""

    name: str = "task_manager"
    description: str = (
        "Query and manage the user's commitments, action items, and promises. "
        "Can list pending tasks, overdue items, and update task status."
    )

    async def list_pending(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """List all pending commitments."""
        commitments = await commitment_service.list_commitments(
            db, user_id, status=CommitmentStatus.PENDING,
        )
        return [self._commitment_to_dict(c) for c in commitments]

    async def list_overdue(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """List overdue commitments (pending + past due date)."""
        now = datetime.now(timezone.utc)
        commitments = await commitment_service.list_commitments(
            db, user_id, status=CommitmentStatus.PENDING, due_before=now,
        )
        return [self._commitment_to_dict(c) for c in commitments]

    async def list_due_soon(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        due_before: datetime,
    ) -> List[Dict[str, Any]]:
        """List commitments due before a given date."""
        commitments = await commitment_service.list_commitments(
            db, user_id, status=CommitmentStatus.PENDING, due_before=due_before,
        )
        return [self._commitment_to_dict(c) for c in commitments]

    @staticmethod
    def _commitment_to_dict(commitment: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": str(commitment.id),
            "commitment_text": commitment.commitment_text,
            "owner": commitment.owner,
            "due_date": commitment.due_date.isoformat() if commitment.due_date else None,
            "created_at": commitment.created_at.isoformat() if getattr(commitment, "created_at", None) else None,
            "status": commitment.status.value,
            "priority": commitment.priority,
            "source": None,
        }

        # Include provenance from the source document so the agent can cite origin
        doc = getattr(commitment, "document", None)
        if doc is not None:
            meta = doc.metadata_ or {}
            result["source"] = {
                "platform": doc.source,
                "subject": meta.get("subject") or meta.get("title"),
                "author": meta.get("author"),
                "timestamp": meta.get("timestamp"),
                "type": meta.get("type"),
            }

        return result
