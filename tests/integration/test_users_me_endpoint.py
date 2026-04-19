"""Integration tests for GET /users/me endpoint."""
import pytest
from httpx import AsyncClient


async def _create_user(
    client: AsyncClient,
    email: str = "me@example.com",
    full_name: str = "Me User",
) -> str:
    """Create a user and return user_id."""
    resp = await client.post("/users/", json={
        "email": email, "full_name": full_name,
    })
    assert resp.status_code == 201
    return resp.json()["id"]


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_get_me_returns_user(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.get(
            "/users/me",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == user_id
        assert data["email"] == "me@example.com"
        assert data["full_name"] == "Me User"
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_get_me_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/users/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_invalid_user(self, client: AsyncClient) -> None:
        import uuid
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            "/users/me",
            headers={"X-User-Id": fake_id},
        )
        assert resp.status_code == 404
