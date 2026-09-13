"""AgentRun model — one row per Strands agent/swarm invocation.

Part of the knowledge-system backoffice (specs/plan-knowledge-backoffice.md). Domain
agents, the I+D agent, reconciliation and peer-agent negotiations all discard their
Strands conversation once they return a summary string — this table is where that
gets persisted instead, via app/services/agent/tracing.py. A negotiation triggered by
another run (ask_peer_agents, negotiate_same_as) sets parent_run_id so it shows up as
a sub-run of whatever run doubted something, rather than a disconnected row.
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, pg_enum


class RunType(str, enum.Enum):
    DOMAIN_AGENT = "domain_agent"
    RD_AGENT = "rd_agent"
    RECONCILIATION = "reconciliation"
    NEGOTIATION = "negotiation"
    CHAT = "chat"


class RunTrigger(str, enum.Enum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    API = "api"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_key: Mapped[str] = mapped_column(Text, nullable=False)
    run_type: Mapped[RunType] = mapped_column(pg_enum(RunType, "run_type_enum"), nullable=False)
    trigger: Mapped[RunTrigger] = mapped_column(pg_enum(RunTrigger, "run_trigger_enum"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        pg_enum(RunStatus, "run_status_enum"),
        default=RunStatus.RUNNING,
        server_default=RunStatus.RUNNING.value,
        nullable=False,
    )
    model_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stats: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    parent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_agent_runs_user_id", "user_id"),
        Index("ix_agent_runs_user_agent", "user_id", "agent_key"),
        Index("ix_agent_runs_user_started", "user_id", "started_at"),
        Index("ix_agent_runs_parent_run_id", "parent_run_id"),
    )
