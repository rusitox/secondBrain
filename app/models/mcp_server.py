"""McpServer model — a user-registered MCP server available as a tool source.

Part of the knowledge-system backoffice (specs/plan-knowledge-backoffice.md). Mirrors
the id_brain_mcp_url/id_brain_mcp_api_key settings that today configure the single
I+D-platform MCP server (app/services/agent/knowledge/rd_agent.py) — those env vars
remain the deploy-time bootstrap; rows here are what the user administers at runtime.

api_key_encrypted is encrypted with app/utils/encryption.encrypt_token/decrypt_token
(Fernet) in the service layer, same as Integration.access_token — never store or
return the plaintext key outside that layer. allowed_tools/rejected_tools map
directly to Strands' MCPClient(tool_filters=...) shape (see rd_agent._build_mcp_client).
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class McpServer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "mcp_servers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_header: Mapped[str] = mapped_column(Text, default="Authorization", server_default="Authorization", nullable=False)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    allowed_tools: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    rejected_tools: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discovered_tools: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    __table_args__ = (
        Index("ix_mcp_servers_user_id", "user_id"),
    )
