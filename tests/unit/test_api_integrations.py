"""Unit tests for integration API endpoints."""
import uuid

import pytest
from httpx import AsyncClient


async def _create_user(client: AsyncClient, email: str = "integ@example.com") -> str:
    resp = await client.post("/users/", json={
        "email": email, "full_name": "Integ User"
    })
    return resp.json()["id"]


class TestCreateIntegration:
    async def test_create_integration_success(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.post(
            "/integrations/",
            json={
                "user_id": user_id,
                "platform": "slack",
                "access_token": "xoxb-secret-token",
            },
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["platform"] == "slack"
        assert data["is_active"] is True
        # Token must NOT be in response
        assert "access_token" not in data
        assert "refresh_token" not in data

    async def test_create_integration_missing_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/integrations/", json={
            "user_id": str(uuid.uuid4()),
            "platform": "slack",
            "access_token": "token",
        })
        assert resp.status_code == 401

    async def test_create_integration_wrong_user(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "owner_int@example.com")
        resp = await client.post(
            "/integrations/",
            json={
                "user_id": str(uuid.uuid4()),
                "platform": "outlook",
                "access_token": "token",
            },
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 403


class TestListIntegrations:
    async def test_list_integrations(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "list_int@example.com")
        headers = {"X-User-Id": user_id}
        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "slack", "access_token": "t1"
        }, headers=headers)
        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "outlook", "access_token": "t2"
        }, headers=headers)

        resp = await client.get("/integrations/", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_integrations_filter_platform(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "filter_int@example.com")
        headers = {"X-User-Id": user_id}
        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "slack", "access_token": "t1"
        }, headers=headers)
        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "outlook", "access_token": "t2"
        }, headers=headers)

        resp = await client.get("/integrations/?platform=slack", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["platform"] == "slack"


class TestUpdateIntegration:
    async def test_toggle_integration_active(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "toggle@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/integrations/", json={
            "user_id": user_id, "platform": "teams", "access_token": "token"
        }, headers=headers)
        iid = create_resp.json()["id"]

        resp = await client.patch(f"/integrations/{iid}", json={
            "is_active": False
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


class TestDeleteIntegration:
    async def test_delete_integration_success(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "del_int@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/integrations/", json={
            "user_id": user_id, "platform": "fathom", "access_token": "token"
        }, headers=headers)
        iid = create_resp.json()["id"]

        resp = await client.delete(f"/integrations/{iid}", headers=headers)
        assert resp.status_code == 204

    async def test_delete_other_users_integration(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "own_del_int@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/integrations/", json={
            "user_id": user_id, "platform": "slack", "access_token": "token"
        }, headers=headers)
        iid = create_resp.json()["id"]

        other_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/integrations/{iid}",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 404
