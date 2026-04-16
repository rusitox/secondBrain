"""Unit tests for user API endpoints."""
import uuid

import pytest
from httpx import AsyncClient


class TestCreateUser:
    async def test_create_user_success(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={
            "email": "new@example.com",
            "full_name": "New User",
            "timezone": "UTC",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["full_name"] == "New User"
        assert "id" in data

    async def test_create_user_duplicate_email(self, client: AsyncClient) -> None:
        payload = {"email": "dup@example.com", "full_name": "First"}
        await client.post("/users/", json=payload)
        resp = await client.post("/users/", json={
            "email": "dup@example.com", "full_name": "Second"
        })
        assert resp.status_code == 409

    async def test_create_user_invalid_email(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={
            "email": "not-an-email",
            "full_name": "Test",
        })
        assert resp.status_code == 422

    async def test_create_user_invalid_timezone(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={
            "email": "tz@example.com",
            "full_name": "Test",
            "timezone": "Invalid/Zone",
        })
        assert resp.status_code == 422


class TestGetUser:
    async def test_get_user_success(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "get@example.com", "full_name": "Get User"
        })
        user_id = create_resp.json()["id"]
        resp = await client.get(
            f"/users/{user_id}",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "get@example.com"

    async def test_get_user_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/users/{fake_id}",
            headers={"X-User-Id": fake_id},
        )
        assert resp.status_code == 404

    async def test_get_user_missing_auth(self, client: AsyncClient) -> None:
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/users/{fake_id}")
        assert resp.status_code == 401

    async def test_get_other_user_forbidden(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "mine@example.com", "full_name": "Mine"
        })
        user_id = create_resp.json()["id"]
        other_id = str(uuid.uuid4())
        resp = await client.get(
            f"/users/{user_id}",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403


class TestUpdateUser:
    async def test_update_user_success(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "upd@example.com", "full_name": "Old Name"
        })
        user_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/users/{user_id}",
            json={"full_name": "New Name"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "New Name"

    async def test_update_user_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/users/{fake_id}",
            json={"full_name": "X"},
            headers={"X-User-Id": fake_id},
        )
        assert resp.status_code == 404

    async def test_update_other_user_forbidden(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "own_upd@example.com", "full_name": "Owner"
        })
        user_id = create_resp.json()["id"]
        other_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/users/{user_id}",
            json={"full_name": "Hacked"},
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403


class TestDeleteUser:
    async def test_delete_user_success(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "del@example.com", "full_name": "Delete Me"
        })
        user_id = create_resp.json()["id"]
        resp = await client.delete(
            f"/users/{user_id}",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 204

        # Verify deleted
        get_resp = await client.get(
            f"/users/{user_id}",
            headers={"X-User-Id": user_id},
        )
        assert get_resp.status_code == 404

    async def test_delete_user_not_found(self, client: AsyncClient) -> None:
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/users/{fake_id}",
            headers={"X-User-Id": fake_id},
        )
        assert resp.status_code == 404

    async def test_delete_other_user_forbidden(self, client: AsyncClient) -> None:
        create_resp = await client.post("/users/", json={
            "email": "own_del@example.com", "full_name": "Owner"
        })
        user_id = create_resp.json()["id"]
        other_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/users/{user_id}",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403
