"""ActionAuditLog — append-only trail for ProposedAction lifecycle events.

No update path exists anywhere in this codebase for this table, by design:
it is the record of what actually happened to an action (proposed, viewed,
approved, rejected, executed, failed), independent of the ProposedAction
row's own current status, which can itself only be read forward.
"""
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ActionAuditLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "action_audit_log"

    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_actions.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(Text, nullable=False)  # proposed|viewed|approved|rejected|executed|failed
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # agent|user|system
    detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_action_audit_log_action_id", "action_id"),
    )
