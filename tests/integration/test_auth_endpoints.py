"""Integration tests for auth API endpoints."""
import uuid

import pytest
from httpx import AsyncClient


async def _create_user(client: AsyncClient, email: str = "auth@example.com") -> str:
    resp = await client.post("/users/", json={
        "email": email, "full_name": "Auth User"
    })
    return resp.json()["id"]


class TestBootstrapEndpoint:
    @pytest.mark.asyncio
    async def test_bootstrap_creates_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.post(
            "/auth/bootstrap",
            json={"name": "test-key"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"].startswith("sb_live_")
        assert len(data["key"]) == 40
        assert data["name"] == "test-key"
        assert data["is_active"] is True
        assert data["key_prefix"] == data["key"][:12]

    @pytest.mark.asyncio
    async def test_bootstrap_invalid_uuid(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/auth/bootstrap",
            json={"name": "test"},
            headers={"X-User-Id": "not-a-uuid"},
        )
        assert resp.status_code == 400


class TestCreateAPIKey:
    @pytest.mark.asyncio
    async def test_create_key_with_x_user_id(self, client: AsyncClient) -> None:
        """In dev mode, can create a key using X-User-Id auth."""
        user_id = await _create_user(client)
        resp = await client.post(
            "/auth/api-keys",
            json={"name": "laptop"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "laptop"
        assert "key" in data
        assert data["key"].startswith("sb_live_")


class TestListAPIKeys:
    @pytest.mark.asyncio
    async def test_list_keys(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        # Create two keys
        await client.post(
            "/auth/api-keys",
            json={"name": "key1"},
            headers={"X-User-Id": user_id},
        )
        await client.post(
            "/auth/api-keys",
            json={"name": "key2"},
            headers={"X-User-Id": user_id},
        )
        resp = await client.get(
            "/auth/api-keys",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == 2
        # Keys should never contain plaintext
        for key in data["keys"]:
            assert "key" not in key or key.get("key") is None


class TestRevokeAPIKey:
    @pytest.mark.asyncio
    async def test_revoke_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        create_resp = await client.post(
            "/auth/api-keys",
            json={"name": "to-revoke"},
            headers={"X-User-Id": user_id},
        )
        key_id = create_resp.json()["id"]
        resp = await client.delete(
            "/auth/api-keys/{0}".format(key_id),
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.delete(
            "/auth/api-keys/{0}".format(uuid.uuid4()),
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404


class TestRegenerateAPIKey:
    @pytest.mark.asyncio
    async def test_regenerate_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        create_resp = await client.post(
            "/auth/api-keys",
            json={"name": "regen-me"},
            headers={"X-User-Id": user_id},
        )
        old_data = create_resp.json()
        old_key = old_data["key"]

        resp = await client.post(
            "/auth/api-keys/{0}/regenerate".format(old_data["id"]),
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        new_data = resp.json()
        assert new_data["key"] != old_key
        assert new_data["name"] == "regen-me"
        assert new_data["is_active"] is True

    @pytest.mark.asyncio
    async def test_regenerate_nonexistent_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.post(
            "/auth/api-keys/{0}/regenerate".format(uuid.uuid4()),
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404
