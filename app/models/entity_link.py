"""EntityLink model — a relationship (or merge) between two Entity rows.

relation_type is free-text rather than an enum: new domain agents add new
relation kinds over time (e.g. a future R&D agent's "collaborates_on") and
that shouldn't require a migration. "same_as" is the merge/dedup relation
produced by the reconciliation engine.
"""
import enum
import uuid

from sqlalchemy import Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, pg_enum


class LinkResolvedBy(str, enum.Enum):
    DETERMINISTIC = "deterministic"
    SWARM = "swarm"
    USER = "user"


class EntityLink(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entity_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entity_id_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    entity_id_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    resolved_by: Mapped[LinkResolvedBy] = mapped_column(
        pg_enum(LinkResolvedBy, "link_resolved_by_enum"), nullable=False,
    )

    __table_args__ = (
        Index("ix_entity_links_user_id", "user_id"),
        Index("ix_entity_links_entity_id_a", "entity_id_a"),
        Index("ix_entity_links_entity_id_b", "entity_id_b"),
    )
