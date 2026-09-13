"""AgentConfig model — per-user override of one agent's model/prompt/tools/MCPs.

Part of the knowledge-system backoffice (specs/plan-knowledge-backoffice.md). A row
here is a *partial override*: every column defaults to NULL, and NULL means "use the
code default" (see app/services/agent/agent_config_service.py for the merge). A user
with no rows at all gets exactly today's hardcoded behavior — that's the property
that makes introducing this table safe. agent_key matches domain_agent.REGISTERED_SOURCES
plus "reconciliation" and "orchestrator", but is a plain Text column (not an enum) so a
new agent doesn't require a migration to become configurable.
"""
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentConfig(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agent_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_key: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled_tools: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    mcp_server_ids: Mapped[List[str]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)

    __table_args__ = (
        Index("ix_agent_configs_user_id", "user_id"),
        Index("ix_agent_configs_user_agent", "user_id", "agent_key", unique=True),
    )
