"""ProcessedDocument — tracks which Documents a knowledge domain agent already extracted.

A separate table rather than a column on Document: Document is shared across
ingestion/retrieval/commitments and its meaning shouldn't shift for a concern
specific to the knowledge subsystem (specs/plan-multi-agent-knowledge.md).
A document that yields zero claims still gets marked processed, so the agent
doesn't re-read it every batch forever.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class ProcessedDocument(UUIDMixin, Base):
    __tablename__ = "knowledge_processed_documents"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_knowledge_processed_documents_user_source", "user_id", "source"),
    )
