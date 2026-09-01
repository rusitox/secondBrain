import enum
import uuid
from typing import TYPE_CHECKING, Optional
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class Platform(str, enum.Enum):
    SLACK = "slack"
    OUTLOOK = "outlook"
    TEAMS = "teams"
    FATHOM = "fathom"
    NOTION = "notion"


class Integration(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "integrations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform_enum", values_callable=lambda obj: [e.value for e in obj]), nullable=False
    )
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Sync scheduling columns
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_interval_minutes: Mapped[int] = mapped_column(default=30)
    last_sync_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="integrations")
