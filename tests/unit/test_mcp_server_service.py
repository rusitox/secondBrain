"""Tests for app.services.mcp_server_service — CRUD + connection testing for
user-registered MCP servers. specs/plan-knowledge-backoffice.md, Phase 3.

MCPClient is always mocked here — never a real network call, same convention
as tests/integration/test_rd_agent.py.
"""
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_server import McpServer
from app.services import mcp_server_service
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


def _fake_mcp_tool(name: str, description: str = "") -> MagicMock:
    tool = MagicMock()
    tool.tool_name = name
    tool.tool_spec = {"name": name, "description": description}
    return tool


class TestCreateMcpServer:
    async def test_encrypts_api_key_at_rest(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp1@example.com")

        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="I+D Platform", url="https://mcp.example.com",
            api_key="super-secret-token",
        )

        assert server.api_key_encrypted != "super-secret-token"
        assert server.api_key_encrypted is not None
        assert "super-secret-token" not in server.api_key_encrypted

        # Confirm nothing plaintext ever hit the DB row itself.
        result = await db_session.execute(select(McpServer).where(McpServer.id == server.id))
        row = result.scalar_one()
        assert "super-secret-token" not in row.api_key_encrypted

    async def test_no_api_key_leaves_column_null(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp2@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="No Auth Server", url="https://mcp.example.com",
        )
        assert server.api_key_encrypted is None

    async def test_defaults(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp3@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://mcp.example.com",
        )
        assert server.auth_header == "Authorization"
        assert server.enabled is True
        assert server.allowed_tools is None
        assert server.rejected_tools is None
        assert server.discovered_tools == []


class TestGetDecryptedApiKey:
    async def test_roundtrips(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp4@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://mcp.example.com", api_key="my-token",
        )
        assert mcp_server_service.get_decrypted_api_key(server) == "my-token"

    async def test_none_when_not_set(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp5@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://mcp.example.com",
        )
        assert mcp_server_service.get_decrypted_api_key(server) is None


class TestListAndGetMcpServers:
    async def test_list_scoped_by_user(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="mcp6a@example.com")
        user_b = await _make_persisted_user(db_session, email="mcp6b@example.com")
        await mcp_server_service.create_mcp_server(db_session, user_a, name="A1", url="https://a1")
        await mcp_server_service.create_mcp_server(db_session, user_a, name="A2", url="https://a2")
        await mcp_server_service.create_mcp_server(db_session, user_b, name="B1", url="https://b1")

        servers_a = await mcp_server_service.list_mcp_servers(db_session, user_a)
        assert {s.name for s in servers_a} == {"A1", "A2"}

    async def test_get_returns_none_for_other_users_server(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="mcp7a@example.com")
        user_b = await _make_persisted_user(db_session, email="mcp7b@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_a, name="A", url="https://a")

        assert await mcp_server_service.get_mcp_server(db_session, user_b, server.id) is None
        assert await mcp_server_service.get_mcp_server(db_session, user_a, server.id) is not None


class TestGetMcpServersByIds:
    async def test_filters_invalid_uuids_and_other_users_rows(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="mcp8a@example.com")
        user_b = await _make_persisted_user(db_session, email="mcp8b@example.com")
        server_a = await mcp_server_service.create_mcp_server(db_session, user_a, name="A", url="https://a")
        server_b = await mcp_server_service.create_mcp_server(db_session, user_b, name="B", url="https://b")

        result = await mcp_server_service.get_mcp_servers_by_ids(
            db_session, user_a, [str(server_a.id), str(server_b.id), "not-a-uuid"],
        )

        assert [s.id for s in result] == [server_a.id]

    async def test_empty_list_returns_empty_without_querying(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp9@example.com")
        assert await mcp_server_service.get_mcp_servers_by_ids(db_session, user_id, []) == []


class TestUpdateMcpServer:
    async def test_partial_update_only_touches_given_fields(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp10@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="Original", url="https://orig.example.com", api_key="orig-key",
        )

        await mcp_server_service.update_mcp_server(db_session, server, name="Renamed")

        assert server.name == "Renamed"
        assert server.url == "https://orig.example.com"
        assert mcp_server_service.get_decrypted_api_key(server) == "orig-key"

    async def test_api_key_update_re_encrypts(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp11@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://s", api_key="old-key",
        )
        old_ciphertext = server.api_key_encrypted

        await mcp_server_service.update_mcp_server(db_session, server, api_key="new-key")

        assert server.api_key_encrypted != old_ciphertext
        assert mcp_server_service.get_decrypted_api_key(server) == "new-key"


class TestDeleteMcpServer:
    async def test_deletes_row(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp12@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="https://s")
        server_id = server.id

        await mcp_server_service.delete_mcp_server(db_session, server)

        assert await mcp_server_service.get_mcp_server(db_session, user_id, server_id) is None


class TestBuildToolFilters:
    async def test_always_includes_extra_rejected(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp13@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://s", allowed_tools=["create_tasks", "list_tasks"],
        )

        filters = mcp_server_service.build_tool_filters(server, extra_rejected=["create_tasks"])

        assert "create_tasks" in filters["rejected"]
        # allowed still lists it — Strands applies allowed first, then
        # excludes rejected from what's left, so it's never re-included.
        assert "create_tasks" in filters["allowed"]

    async def test_no_allowed_tools_omits_allowed_key(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp14@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="https://s")

        filters = mcp_server_service.build_tool_filters(server)

        assert "allowed" not in filters
        assert filters["rejected"] == []

    async def test_merges_server_and_extra_rejected(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp15@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://s", rejected_tools=["delete_everything"],
        )

        filters = mcp_server_service.build_tool_filters(server, extra_rejected=["create_tasks"])

        assert set(filters["rejected"]) == {"delete_everything", "create_tasks"}


class TestConnectionTest:
    async def test_success_returns_ok_and_tool_list(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp16@example.com")
        server = await mcp_server_service.create_mcp_server(
            db_session, user_id, name="S", url="https://mcp.example.com", api_key="tok",
        )
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = [
            _fake_mcp_tool("list_initiatives", "List active initiatives"),
        ]

        with patch("strands.tools.mcp.MCPClient", return_value=mock_client) as mock_cls:
            result = await mcp_server_service.test_connection(server)

        assert result["status"] == "ok"
        assert result["tools"] == [{"name": "list_initiatives", "description": "List active initiatives"}]
        mock_client.start.assert_called_once()
        mock_client.stop.assert_called_once()
        # The decrypted key reaches the client as a bearer header, never logged/returned.
        _, kwargs = mock_cls.call_args
        assert kwargs["headers"] == {"Authorization": "Bearer tok"}

    async def test_client_construction_failure_returns_error_status_without_raising(
        self, db_session: AsyncSession,
    ) -> None:
        """MCPClient(...) itself can raise (e.g. a malformed url) — this must
        still honor test_connection's "never raises" contract, not just
        failures from .start()/.list_tools_sync()."""
        user_id = await _make_persisted_user(db_session, email="mcp17b@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="not-a-url")

        with patch("strands.tools.mcp.MCPClient", side_effect=ValueError("bad url")):
            result = await mcp_server_service.test_connection(server)

        assert result == {"status": "error: bad url", "tools": []}

    async def test_start_failure_returns_error_status_and_still_stops(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp17@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="https://s")
        mock_client = MagicMock()
        mock_client.start.side_effect = ConnectionError("unreachable")

        with patch("strands.tools.mcp.MCPClient", return_value=mock_client):
            result = await mcp_server_service.test_connection(server)

        assert result["status"].startswith("error:")
        assert result["tools"] == []
        mock_client.stop.assert_called_once()

    async def test_extra_rejected_reaches_tool_filters(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp18@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="https://s")
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = []

        with patch("strands.tools.mcp.MCPClient", return_value=mock_client) as mock_cls:
            await mcp_server_service.test_connection(server, extra_rejected=["create_tasks"])

        _, kwargs = mock_cls.call_args
        assert "create_tasks" in kwargs["tool_filters"]["rejected"]


class TestRecordConnectionTest:
    async def test_persists_status_and_tools(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="mcp19@example.com")
        server = await mcp_server_service.create_mcp_server(db_session, user_id, name="S", url="https://s")

        await mcp_server_service.record_connection_test(
            db_session, server, status="ok", discovered_tools=[{"name": "list_tasks", "description": ""}],
        )

        assert server.last_status == "ok"
        assert server.discovered_tools == [{"name": "list_tasks", "description": ""}]
        assert server.last_checked_at is not None
