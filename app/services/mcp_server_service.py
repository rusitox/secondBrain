"""CRUD + connection-testing for user-registered MCP servers.

specs/plan-knowledge-backoffice.md, Phase 3. Mirrors app/services/integration_service.py's
shape: the model column is a plain Text, encryption happens here in the service layer via
app.utils.encryption (Fernet) — never in the model, never returned by get_decrypted_api_key's
callers to an API response (see app/api/schemas — McpServerRead must omit api_key_encrypted
the same way IntegrationRead omits access_token/refresh_token).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_server import McpServer
from app.utils.encryption import decrypt_token, encrypt_token

if TYPE_CHECKING:
    from strands.tools.mcp.mcp_client import ToolFilters

logger = logging.getLogger(__name__)


async def create_mcp_server(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    url: str,
    auth_header: str = "Authorization",
    api_key: Optional[str] = None,
    enabled: bool = True,
    allowed_tools: Optional[List[str]] = None,
    rejected_tools: Optional[List[str]] = None,
) -> McpServer:
    server = McpServer(
        user_id=user_id,
        name=name,
        url=url,
        auth_header=auth_header,
        api_key_encrypted=encrypt_token(api_key) if api_key else None,
        enabled=enabled,
        allowed_tools=allowed_tools,
        rejected_tools=rejected_tools,
    )
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


async def get_mcp_server(db: AsyncSession, user_id: uuid.UUID, server_id: uuid.UUID) -> Optional[McpServer]:
    result = await db.execute(
        select(McpServer).where(McpServer.id == server_id, McpServer.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_mcp_servers(db: AsyncSession, user_id: uuid.UUID) -> List[McpServer]:
    result = await db.execute(
        select(McpServer).where(McpServer.user_id == user_id).order_by(McpServer.created_at)
    )
    return list(result.scalars().all())


async def get_mcp_servers_by_ids(
    db: AsyncSession, user_id: uuid.UUID, server_ids: List[str],
) -> List[McpServer]:
    """Look up a user's servers among the given ids, silently dropping any
    that don't parse as UUIDs or don't belong to this user — a stale/invalid
    id in AgentConfig.mcp_server_ids (e.g. the server was deleted since) is
    something the caller (rd_agent) falls back around, not an error here."""
    valid_ids = []
    for raw_id in server_ids:
        try:
            valid_ids.append(uuid.UUID(raw_id))
        except ValueError:
            logger.warning("get_mcp_servers_by_ids: skipping invalid uuid %r", raw_id)
    if not valid_ids:
        return []
    result = await db.execute(
        select(McpServer).where(McpServer.id.in_(valid_ids), McpServer.user_id == user_id)
    )
    return list(result.scalars().all())


async def update_mcp_server(
    db: AsyncSession,
    server: McpServer,
    name: Optional[str] = None,
    url: Optional[str] = None,
    auth_header: Optional[str] = None,
    api_key: Optional[str] = None,
    enabled: Optional[bool] = None,
    allowed_tools: Optional[List[str]] = None,
    rejected_tools: Optional[List[str]] = None,
) -> McpServer:
    if name is not None:
        server.name = name
    if url is not None:
        server.url = url
    if auth_header is not None:
        server.auth_header = auth_header
    if api_key is not None:
        server.api_key_encrypted = encrypt_token(api_key)
    if enabled is not None:
        server.enabled = enabled
    if allowed_tools is not None:
        server.allowed_tools = allowed_tools
    if rejected_tools is not None:
        server.rejected_tools = rejected_tools
    await db.flush()
    await db.refresh(server)
    return server


async def delete_mcp_server(db: AsyncSession, server: McpServer) -> None:
    await db.delete(server)
    await db.flush()


def get_decrypted_api_key(server: McpServer) -> Optional[str]:
    """Decrypt api_key_encrypted for use building an MCP client connection.
    Never expose the return value via an API response."""
    if not server.api_key_encrypted:
        return None
    return decrypt_token(server.api_key_encrypted)


def _describe_tool(t: Any) -> Dict[str, str]:
    spec = getattr(t, "tool_spec", None) or {}
    description = spec.get("description", "") if isinstance(spec, dict) else ""
    return {"name": getattr(t, "tool_name", "") or "", "description": description}


def build_tool_filters(server: McpServer, extra_rejected: Optional[List[str]] = None) -> "ToolFilters":
    """Build a Strands ToolFilters dict from a server's own allowed/rejected
    lists, always adding extra_rejected (e.g. rd_agent.EXCLUDED_MCP_TOOLS) to
    whatever the server rejects.

    Strands applies 'allowed' first, then excludes 'rejected' from what's
    left (see strands.tools.mcp.mcp_client.ToolFilters's own docstring) — so
    listing a name in both never re-includes it. This is what makes
    extra_rejected a real invariant rather than something a server's own
    allowed_tools could accidentally override.
    """
    rejected = set(server.rejected_tools or []) | set(extra_rejected or [])
    filters: "ToolFilters" = {"rejected": sorted(rejected)}  # type: ignore[typeddict-item]
    if server.allowed_tools:
        filters["allowed"] = list(server.allowed_tools)
    return filters


async def test_connection(
    server: McpServer, extra_rejected: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Connect to an MCP server and list its tools — never writes to the DB
    itself (see record_connection_test for persisting the outcome); the
    caller decides whether/when to persist, same split as
    tracing.start_run/finish_run being separate from the work they trace.

    Returns {"status": "ok"} or {"status": "error: <message>"}, plus
    "tools": [{"name": ..., "description": ...}] (empty on error).
    """
    from strands.tools.mcp import MCPClient

    client: Any = None
    try:
        api_key = get_decrypted_api_key(server)
        headers = {server.auth_header: f"Bearer {api_key}"} if api_key else {}
        tool_filters = build_tool_filters(server, extra_rejected=extra_rejected)
        # MCPClient(...) itself can raise (e.g. ValueError on a malformed
        # url) — constructing it inside this try is what makes that a
        # returned {"status": "error: ..."} instead of an exception
        # breaking this function's "never raises" contract.
        client = MCPClient(url=server.url, headers=headers, tool_filters=tool_filters)
        client.start()
        tools = client.list_tools_sync()
        return {"status": "ok", "tools": [_describe_tool(t) for t in tools]}
    except Exception as e:
        logger.warning("test_connection failed for mcp_server=%s: %s", server.id, e)
        return {"status": f"error: {e}", "tools": []}
    finally:
        if client is not None:
            try:
                client.stop(None, None, None)
            except Exception:
                logger.exception("test_connection: failed to stop MCP client for mcp_server=%s", server.id)


async def record_connection_test(
    db: AsyncSession, server: McpServer, status: str, discovered_tools: List[Dict[str, Any]],
) -> McpServer:
    """Persist the outcome of a connection test (see rd_agent.test_mcp_server_connection
    for what actually opens the connection — this only records the result)."""
    server.last_checked_at = datetime.now(timezone.utc)
    server.last_status = status[:2000]
    server.discovered_tools = discovered_tools
    await db.flush()
    await db.refresh(server)
    return server
