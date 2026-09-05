"""PendingQuestion model — the resolution-ladder state machine.

A doubt is never asked to the human cold. It is created with target=PEER_AGENTS;
consult_knowledge_base / ask_peer_agents (Phase 1) may resolve it without ever
reaching a person. Only when nothing upstream resolves it does target flip to
HUMAN — and even then candidate_answer/candidate_confidence carry the best
guess so far, so the human is asked to validate rather than answer cold.
See specs/plan-multi-agent-knowledge.md, "Escalada de resolución de dudas".
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class QuestionTarget(str, enum.Enum):
    PEER_AGENTS = "peer_agents"
    HUMAN = "human"


class QuestionStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    DISMISSED = "dismissed"


class ResolvedBy(str, enum.Enum):
    KNOWLEDGE_BASE = "knowledge_base"
    PEER_SWARM = "peer_swarm"
    HUMAN = "human"


class PendingQuestion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "pending_questions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    raised_by_agent: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    target: Mapped[QuestionTarget] = mapped_column(
        Enum(QuestionTarget, name="question_target_enum", values_callable=lambda obj: [e.value for e in obj]),
        default=QuestionTarget.PEER_AGENTS,
        server_default=QuestionTarget.PEER_AGENTS.value,
        nullable=False,
    )
    candidate_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus, name="question_status_enum", values_callable=lambda obj: [e.value for e in obj]),
        default=QuestionStatus.OPEN,
        server_default=QuestionStatus.OPEN.value,
        nullable=False,
    )
    resolved_by: Mapped[Optional[ResolvedBy]] = mapped_column(
        Enum(ResolvedBy, name="resolved_by_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pending_questions_user_id", "user_id"),
        Index("ix_pending_questions_user_status", "user_id", "status"),
    )
