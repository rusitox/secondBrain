import uuid
from typing import TYPE_CHECKING, Any, Dict, List

from sqlalchemy import Index, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.commitment import Commitment
    from app.models.user import User


EMBEDDING_DIMENSION = 1536


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSION))
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), default="")
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="documents")
    commitments: Mapped[List["Commitment"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_documents_embedding_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_documents_user_source",
            "user_id",
            "source",
            "source_id",
            unique=True,
        ),
    )
