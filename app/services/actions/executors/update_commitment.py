"""update_commitment executor — lets the agent correct a misfiled
commitment (wrong owner, wrong text, already resolved) through the same
propose/approve path as notion_publish, never by writing to the DB
directly from a tool. See app.services.actions.registry's module
docstring for why this file is never imported from strands_tools.py.
"""
import logging
import uuid
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.commitment import CommitmentUpdate
from app.models.commitment import CommitmentStatus
from app.services import commitment_service
from app.services.actions.registry import register

logger = logging.getLogger(__name__)


class UpdateCommitmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commitment_id: uuid.UUID
    owner: Optional[str] = Field(default=None, max_length=200)
    status: Optional[CommitmentStatus] = None
    commitment_text: Optional[str] = Field(default=None, max_length=2000)
    delivered_to: Optional[str] = Field(default=None, max_length=200)


class UpdateCommitmentExecutor:
    action_type = "update_commitment"
    version = "1"
    payload_model: Type[BaseModel] = UpdateCommitmentPayload
    risk = "low"

    async def execute(
        self, db: AsyncSession, user_id: uuid.UUID, payload: BaseModel,
    ) -> Dict[str, Any]:
        assert isinstance(payload, UpdateCommitmentPayload)

        commitment = await commitment_service.get_commitment(db, payload.commitment_id)
        if commitment is None or commitment.user_id != user_id:
            return {"error": "commitment not found"}

        update = CommitmentUpdate(
            owner=payload.owner,
            status=payload.status,
            commitment_text=payload.commitment_text,
            delivered_to=payload.delivered_to,
        )
        try:
            updated = await commitment_service.update_commitment(db, commitment, update)
        except ValueError as e:
            return {"error": str(e)}

        return {
            "commitment_id": str(updated.id),
            "owner": updated.owner,
            "status": updated.status.value,
            "commitment_text": updated.commitment_text,
            "delivered_to": updated.delivered_to,
        }


register(UpdateCommitmentExecutor())
