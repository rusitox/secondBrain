import enum
import uuid
from typing import TYPE_CHECKING, Optional
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class CommitmentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Commitment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "commitments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    commitment_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(Text, default="unknown")
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[CommitmentStatus] = mapped_column(
        Enum(CommitmentStatus, name="commitment_status_enum", values_callable=lambda obj: [e.value for e in obj]),
        default=CommitmentStatus.PENDING,
    )
    priority: Mapped[int] = mapped_column(Integer, default=3)
    notion_page_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, default=None,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="commitments")
    document: Mapped[Optional["Document"]] = relationship(
        back_populates="commitments"
    )
