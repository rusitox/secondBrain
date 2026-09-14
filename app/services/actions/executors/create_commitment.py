"""create_commitment executor — lets the agent add a task to the backlog
(description, optional due date, optional recipient) through the same
propose/approve path as notion_publish/update_commitment, never by writing
to the DB directly from a tool. See app.services.actions.registry's module
docstring for why this file is never imported from strands_tools.py.

owner is always "assistant" here — not a payload field — distinguishing
agent-created backlog items from commitments the passive detector finds in
ingested documents (where owner is whoever made the promise).
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.commitment import CommitmentCreate
from app.services import commitment_service
from app.services.actions.registry import register

logger = logging.getLogger(__name__)


class CreateCommitmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commitment_text: str = Field(max_length=2000)
    due_date: Optional[datetime] = None
    delivered_to: Optional[str] = Field(default=None, max_length=200)


class CreateCommitmentExecutor:
    action_type = "create_commitment"
    version = "1"
    payload_model: Type[BaseModel] = CreateCommitmentPayload
    risk = "low"

    async def execute(
        self, db: AsyncSession, user_id: uuid.UUID, payload: BaseModel,
    ) -> Dict[str, Any]:
        assert isinstance(payload, CreateCommitmentPayload)

        commitment = await commitment_service.create_commitment(
            db, CommitmentCreate(
                user_id=user_id,
                commitment_text=payload.commitment_text,
                owner="assistant",
                due_date=payload.due_date,
                delivered_to=payload.delivered_to,
            ),
        )
        return {
            "commitment_id": str(commitment.id),
            "commitment_text": commitment.commitment_text,
            "owner": commitment.owner,
            "due_date": commitment.due_date.isoformat() if commitment.due_date else None,
            "delivered_to": commitment.delivered_to,
            "status": commitment.status.value,
        }


register(CreateCommitmentExecutor())
