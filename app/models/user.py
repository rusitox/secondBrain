import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.api_key import APIKey
    from app.models.commitment import Commitment
    from app.models.document import Document
    from app.models.identity import Identity
    from app.models.integration import Integration


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

    # Onboarding state
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
    )
    onboarding_step: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
    )

    # Preferences and Notion config stored as JSON text
    # (PostgreSQL JSONB in production, TEXT in SQLite for tests)
    preferences_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    notion_config_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )

    @property
    def preferences(self) -> Dict[str, Any]:
        """Parse preferences JSON, return empty dict if null."""
        if not self.preferences_json:
            return {}
        try:
            return json.loads(self.preferences_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @preferences.setter
    def preferences(self, value: Dict[str, Any]) -> None:
        self.preferences_json = json.dumps(value) if value is not None else None

    @property
    def notion_config(self) -> Optional[Dict[str, Any]]:
        """Parse Notion config JSON."""
        if not self.notion_config_json:
            return None
        try:
            return json.loads(self.notion_config_json)
        except (json.JSONDecodeError, TypeError):
            return None

    @notion_config.setter
    def notion_config(self, value: Optional[Dict[str, Any]]) -> None:
        self.notion_config_json = json.dumps(value) if value else None

    # Relationships
    identities: Mapped[List["Identity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    integrations: Mapped[List["Integration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents: Mapped[List["Document"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    commitments: Mapped[List["Commitment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["APIKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
