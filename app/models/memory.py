import uuid
from typing import List, Optional

from sqlalchemy import Index, SmallInteger, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin, UUIDMixin

MEMORY_EMBEDDING_DIMENSION = 1536


class Memory(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[List] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    source_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    importance: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    embedding = mapped_column(Vector(MEMORY_EMBEDDING_DIMENSION), nullable=True)

    __table_args__ = (
        Index("ix_memories_user_id", "user_id"),
    )
