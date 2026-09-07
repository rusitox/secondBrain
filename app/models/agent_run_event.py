"""AgentRunEvent model — one ordered step within an AgentRun's conversation.

Serialized from a Strands Agent's `.messages` (assistant text, tool_use, tool_result
blocks) or from a Swarm's node results (handoff, verdict) by
app/services/agent/tracing.py. Immutable once written — no TimestampMixin, since
there is no updated_at concept for a log line (see ProcessedDocument for the same
UUIDMixin-only pattern).
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, pg_enum


class RunEventType(str, enum.Enum):
    ASSISTANT_TEXT = "assistant_text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    HANDOFF = "handoff"
    VERDICT = "verdict"
    ERROR = "error"


class AgentRunEvent(UUIDMixin, Base):
    __tablename__ = "agent_run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[RunEventType] = mapped_column(
        pg_enum(RunEventType, "run_event_type_enum"), nullable=False
    )
    actor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_run_events_run_id", "run_id"),
        Index("ix_agent_run_events_run_seq", "run_id", "seq"),
    )
