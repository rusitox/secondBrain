import enum
import uuid
from datetime import datetime
from typing import Type, TypeVar

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

E = TypeVar("E", bound=enum.Enum)


def pg_enum(enum_cls: Type[E], name: str) -> Enum:
    """Postgres ENUM column type storing an str-Enum's .value, not its name.

    Centralizes the values_callable incantation every str-Enum column added
    since app/models/entity*.py and pending_question.py needs, so it's
    written once instead of copy-pasted per column. commitment.py predates
    this helper and still has its own inline copy of the same pattern —
    not migrated here, since that's an unrelated change to already-shipped
    code rather than something this work touches.
    """
    return Enum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
