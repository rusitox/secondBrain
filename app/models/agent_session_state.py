"""AgentSessionState model — the paused Strands Agent snapshot a session's
next request resumes from after a request_user_input interrupt.

A session has one snapshot but can raise many UserInteraction rows over its
life, and the snapshot (full message history via Agent.take_snapshot()) is
comparatively large — hence its own table rather than a column on
UserInteraction. Independently useful too: reloading a snapshot is a
strictly better continuation mechanism than the flattened-text-history
replay StrandsOrchestrator._resolve_session does today, since it preserves
tool-call structure Strands itself needs to stay well-formed.
"""
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentSessionState(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agent_session_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)  # Snapshot.to_dict()
    # Guards against loading a snapshot whose message/tool-call shape a
    # different Strands version might not deserialize compatibly — see
    # strands_orchestrator.py's snapshot-load path.
    strands_version: Mapped[str] = mapped_column(Text, nullable=False)
    awaiting_input: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_agent_session_states_session_id"),
    )
