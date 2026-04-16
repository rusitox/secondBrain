from typing import TYPE_CHECKING, List

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.commitment import Commitment
    from app.models.document import Document
    from app.models.identity import Identity
    from app.models.integration import Integration


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

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
