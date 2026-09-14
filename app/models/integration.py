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
    # Optional User Token (xoxp-) for platforms that need it for extended access.
    # Slack: user_token grants access to personal DMs; access_token is the Bot Token.
    user_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The connected account's own id on the external platform (e.g. Slack's
    # "user_id" from auth.test) — needed to tell "a message that mentions
    # me" from "a message that mentions someone else", which a resolved
    # display name alone can't disambiguate reliably. Populated lazily by
    # the sync scheduler (see BaseConnector.get_own_account_id); nullable
    # because most platforms don't implement it and existing rows predate it.
    external_account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # OAuth 2.1 client id from dynamic client registration (Fathom's MCP
    # server) — needed to request a refresh_token grant later. Nullable
    # because every other platform still uses a static token/MSAL cache.
    oauth_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # When the current access_token expires — Fathom's isn't a JWT we can
    # decode like MSAL's (see token_refresh.is_token_expiring_soon), so the
    # expiry has to be tracked out-of-band from the token grant response.
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
