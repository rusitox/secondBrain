"""ProposedAction model — an external action the agent proposed but cannot
execute itself. See app/services/actions/registry.py for the executor
whitelist and the actual commit gate:

    propose (LLM tool, strands_tools.py) -> preview (artifact, client-rendered)
    -> approve (POST /interactions/actions/{id}/approve, human, non-LLM)
    -> execute (registry executor, non-LLM)

No tool in strands_tools.py can transition a row past "proposed" — that is
the entire point of this model existing separately from just calling an
executor directly from a tool.
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, pg_enum


class ActionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ProposedAction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "proposed_actions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # No FK — sessions are ephemeral, same reasoning as ConversationTurn.session_id.
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    interaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_interactions.id", ondelete="SET NULL"), nullable=True,
    )
    action_type: Mapped[str] = mapped_column(Text, nullable=False)  # registry key
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)  # executor-validated
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    artifact: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)  # a validated ui_protocol Artifact
    risk: Mapped[str] = mapped_column(Text, nullable=False)  # "low" | "high"
    status: Mapped[ActionStatus] = mapped_column(
        pg_enum(ActionStatus, "action_status_enum"),
        default=ActionStatus.PROPOSED,
        server_default=ActionStatus.PROPOSED.value,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    executor_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_proposed_actions_user_status", "user_id", "status"),
        UniqueConstraint("idempotency_key", name="uq_proposed_actions_idempotency_key"),
    )
