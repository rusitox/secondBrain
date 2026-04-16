import uuid
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class Identity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    persona_description: Mapped[str] = mapped_column(Text, default="")
    tone_guidelines: Mapped[str] = mapped_column(Text, default="")
    heuristics: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="identities")
