"""Unit tests for CLI API client."""
import pytest
import respx
from httpx import Response

from cli.api_client import APIClient, APIError


@pytest.fixture
def api() -> APIClient:
    return APIClient(server_url="http://test:8000", user_id="test-user-id")


class TestAPIClientHeaders:
    def test_headers_include_user_id(self) -> None:
        api = APIClient(server_url="http://test:8000", user_id="abc-123")
        headers = api._headers()
        assert headers["X-User-Id"] == "abc-123"

    def test_headers_without_user_id(self) -> None:
        api = APIClient(server_url="http://test:8000")
        headers = api._headers()
        assert "X-User-Id" not in headers

    def test_set_user_id(self) -> None:
        api = APIClient(server_url="http://test:8000")
        api.set_user_id("new-id")
        assert api._headers()["X-User-Id"] == "new-id"


class TestHealthCheck:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_success(self, api: APIClient) -> None:
        respx.get("http://test:8000/").mock(
            return_value=Response(200, json={"status": "ok"})
        )
        assert await api.health_check() is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_failure(self, api: APIClient) -> None:
        respx.get("http://test:8000/").mock(
            return_value=Response(500, json={"detail": "error"})
        )
        assert await api.health_check() is False


class TestUserEndpoints:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_user(self, api: APIClient) -> None:
        respx.post("http://test:8000/users/").mock(
            return_value=Response(201, json={
                "id": "uuid-1", "email": "a@b.com", "full_name": "Test",
                "timezone": "UTC", "created_at": "2026-01-01T00:00:00",
            })
        )
        result = await api.create_user("a@b.com", "Test", "UTC")
        assert result["id"] == "uuid-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_user_stats(self, api: APIClient) -> None:
        respx.get("http://test:8000/users/u1/stats").mock(
            return_value=Response(200, json={
                "documents_total": 10, "commitments_pending": 2,
                "commitments_overdue": 1, "integrations_active": 3,
                "integrations_total": 4, "last_sync": None,
            })
        )
        result = await api.get_user_stats("u1")
        assert result["documents_total"] == 10


class TestIdentityEndpoints:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_identity(self, api: APIClient) -> None:
        respx.post("http://test:8000/users/u1/identity").mock(
            return_value=Response(201, json={
                "id": "id-1", "user_id": "u1",
                "persona_description": "CTO",
                "tone_guidelines": "Direct",
                "heuristics": {}, "created_at": "now", "updated_at": "now",
            })
        )
        result = await api.create_identity("u1", "CTO", "Direct")
        assert result["persona_description"] == "CTO"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_identity_not_found(self, api: APIClient) -> None:
        respx.get("http://test:8000/users/u1/identity").mock(
            return_value=Response(404, json={"detail": "Not found"})
        )
        result = await api.get_identity("u1")
        assert result is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_update_identity(self, api: APIClient) -> None:
        respx.patch("http://test:8000/users/u1/identity").mock(
            return_value=Response(200, json={
                "id": "id-1", "user_id": "u1",
                "persona_description": "New",
                "tone_guidelines": "Casual",
                "heuristics": {}, "created_at": "now", "updated_at": "now",
            })
        )
        result = await api.update_identity("u1", persona_description="New")
        assert result["persona_description"] == "New"


class TestIntegrationEndpoints:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_integration(self, api: APIClient) -> None:
        respx.post("http://test:8000/integrations/").mock(
            return_value=Response(201, json={
                "id": "int-1", "user_id": "u1", "platform": "slack",
                "last_sync_at": None, "is_active": True,
                "created_at": "now", "updated_at": "now",
            })
        )
        result = await api.create_integration("u1", "slack", "xoxb-token")
        assert result["platform"] == "slack"

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_integrations(self, api: APIClient) -> None:
        respx.get("http://test:8000/integrations/").mock(
            return_value=Response(200, json=[
                {"id": "1", "platform": "slack"},
                {"id": "2", "platform": "outlook"},
            ])
        )
        result = await api.list_integrations()
        assert len(result) == 2


class TestSyncEndpoints:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_platform(self, api: APIClient) -> None:
        respx.post("http://test:8000/ingest/sync/slack").mock(
            return_value=Response(200, json={
                "documents_created": 50, "documents_updated": 0,
                "documents_skipped": 0, "chunks_total": 120,
                "commitments_detected": 3,
            })
        )
        result = await api.sync_platform("slack")
        assert result["documents_created"] == 50
        assert result["commitments_detected"] == 3


class TestQueryEndpoints:
    @pytest.mark.asyncio
    @respx.mock
    async def test_agent_query(self, api: APIClient) -> None:
        respx.post("http://test:8000/agent/query").mock(
            return_value=Response(200, json={
                "answer": "You have 2 tasks.",
                "tools_used": ["memory", "tasks"],
                "sources": [], "query": "What's pending?",
            })
        )
        result = await api.agent_query("What's pending?")
        assert "answer" in result


class TestErrorHandling:
    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error_raised(self, api: APIClient) -> None:
        respx.get("http://test:8000/users/bad-id").mock(
            return_value=Response(404, json={"detail": "User not found"})
        )
        with pytest.raises(APIError) as exc_info:
            await api.get_user("bad-id")
        assert exc_info.value.status_code == 404
        assert "User not found" in exc_info.value.detail

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error_422(self, api: APIClient) -> None:
        respx.post("http://test:8000/users/").mock(
            return_value=Response(422, json={"detail": "Validation error"})
        )
        with pytest.raises(APIError) as exc_info:
            await api.create_user("bad-email", "", "")
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    @respx.mock
    async def test_204_returns_empty_dict(self, api: APIClient) -> None:
        respx.delete("http://test:8000/integrations/int-1").mock(
            return_value=Response(204)
        )
        result = await api.delete_integration("int-1")
        # Should not raise
