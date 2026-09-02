"""ConversationTurn model — stores each agent interaction turn per session."""
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ConversationTurn(UUIDMixin, TimestampMixin, Base):
    """One turn (user or assistant) within an agent conversation session.

    session_id is a client-generated UUID that groups turns into a logical
    session. It carries no FK because sessions are ephemeral — the UUID is
    the only identity.
    """

    __tablename__ = "conversation_turns"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )

    __table_args__ = (
        Index("ix_conversation_turns_user_session", "user_id", "session_id"),
        Index("ix_conversation_turns_session_created", "session_id", "created_at"),
    )
