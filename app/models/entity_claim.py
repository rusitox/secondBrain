"""EntityClaim model — one source's assertion about an Entity, with provenance.

Claims are never overwritten in place: a contradiction becomes a second claim
with status=DISPUTED rather than silently replacing the earlier one, so the
reconciliation engine (specs/plan-multi-agent-knowledge.md, Phase 4) has both
sides of a disagreement to work with.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, pg_enum


class ClaimStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    CONFIRMED_BY_USER = "confirmed_by_user"


class EntityClaim(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entity_claims"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        pg_enum(ClaimStatus, "claim_status_enum"),
        default=ClaimStatus.ACTIVE,
        server_default=ClaimStatus.ACTIVE.value,
        nullable=False,
    )
    asserted_by_agent: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_entity_claims_entity_id", "entity_id"),
        Index("ix_entity_claims_user_id", "user_id"),
    )
