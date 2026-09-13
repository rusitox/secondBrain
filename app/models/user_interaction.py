"""UserInteraction model — a runtime request for structured input from the
user, raised mid-conversation by the request_user_input tool via Strands'
native interrupt mechanism (see app/services/agent/strands_orchestrator.py).

Deliberately NOT a PendingQuestion. PendingQuestion is a resolution-ladder
state machine for knowledge-graph doubts raised by background domain agents
(no session, no expiry, answered via confirm_pending_answer which branches
on `context` keys to decide whether to write a claim or a same_as link). A
UserInteraction is session-bound, time-boxed, and answering one must never
accidentally trigger that claim-writing branch — putting both concepts in
one table, differentiated only by which JSON keys happen to be present,
would make that one careless key away from happening. Two tables makes it
structurally impossible; see also app/models/agent_session_state.py, which
holds the paused Agent snapshot this interaction's answer resumes.
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, pg_enum


class InteractionStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class UserInteraction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "user_interactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # No FK — sessions are ephemeral and identified only by this UUID, same
    # reasoning as ConversationTurn.session_id.
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    turn_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation_turns.id", ondelete="SET NULL"), nullable=True,
    )
    # Strands' Interrupt.id — the correlation key between this row and the
    # exact tool call awaiting a response. tool_use_id is kept alongside it
    # for observability even though interrupt_id alone identifies the row.
    interrupt_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_use_id: Mapped[str] = mapped_column(Text, nullable=False)
    spec: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)  # a validated UIRequest
    answer: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)  # {field_key: value}
    status: Mapped[InteractionStatus] = mapped_column(
        pg_enum(InteractionStatus, "interaction_status_enum"),
        default=InteractionStatus.OPEN,
        server_default=InteractionStatus.OPEN.value,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_via: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "ui" | "voice" | "cli"

    __table_args__ = (
        Index("ix_user_interactions_user_status", "user_id", "status"),
        Index("ix_user_interactions_session", "session_id"),
        UniqueConstraint("session_id", "interrupt_id", name="uq_user_interactions_session_interrupt"),
    )
