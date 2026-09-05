"""Entity model — canonical knowledge-graph node (person, project, topic, ...).

Part of the multi-agent knowledge system (see specs/plan-multi-agent-knowledge.md).
Domain agents propose Entity rows; EntityClaim rows carry the provenance for
whatever each source believes about an entity. `confidence` is the aggregate
"solidity" score, recalculated during reconciliation as claims corroborate or
contradict each other.
"""
import enum
import uuid
from typing import Any, Dict, List

from sqlalchemy import Enum, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin, UUIDMixin

ENTITY_EMBEDDING_DIMENSION = 1536


class EntityType(str, enum.Enum):
    PERSON = "person"
    PROJECT = "project"
    INITIATIVE = "initiative"
    TOPIC = "topic"
    ORGANIZATION = "organization"


class Entity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[List[str]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    attributes: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    embedding = mapped_column(Vector(ENTITY_EMBEDDING_DIMENSION), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)

    __table_args__ = (
        Index("ix_entities_user_id", "user_id"),
        Index("ix_entities_user_type", "user_id", "entity_type"),
    )
