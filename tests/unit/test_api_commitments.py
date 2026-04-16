"""Unit tests for commitment API endpoints."""
import uuid

import pytest
from httpx import AsyncClient


async def _create_user(client: AsyncClient, email: str = "commit@example.com") -> str:
    resp = await client.post("/users/", json={
        "email": email, "full_name": "Commit User"
    })
    return resp.json()["id"]


class TestCreateCommitment:
    async def test_create_commitment_success(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.post(
            "/commitments/",
            json={
                "user_id": user_id,
                "commitment_text": "Send the report",
                "priority": 2,
            },
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["commitment_text"] == "Send the report"
        assert data["status"] == "pending"
        assert data["priority"] == 2

    async def test_create_commitment_missing_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/commitments/", json={
            "user_id": str(uuid.uuid4()),
            "commitment_text": "Test",
        })
        assert resp.status_code == 401

    async def test_create_commitment_wrong_user(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "owner@example.com")
        other_id = str(uuid.uuid4())
        resp = await client.post(
            "/commitments/",
            json={"user_id": other_id, "commitment_text": "Test"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 403


class TestListCommitments:
    async def test_list_commitments(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "list@example.com")
        headers = {"X-User-Id": user_id}
        await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Task 1"
        }, headers=headers)
        await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Task 2"
        }, headers=headers)

        resp = await client.get("/commitments/", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_commitments_filter_by_status(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "filter@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Task A"
        }, headers=headers)
        cid = create_resp.json()["id"]

        # Complete it
        await client.patch(f"/commitments/{cid}", json={
            "status": "completed"
        }, headers=headers)

        # Create another pending
        await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Task B"
        }, headers=headers)

        # Filter pending only
        resp = await client.get("/commitments/?status=pending", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["commitment_text"] == "Task B"


class TestUpdateCommitment:
    async def test_update_status_to_completed(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "upd_commit@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Finish report"
        }, headers=headers)
        cid = create_resp.json()["id"]

        resp = await client.patch(f"/commitments/{cid}", json={
            "status": "completed"
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    async def test_cannot_update_completed_commitment(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "no_reopen@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Done task"
        }, headers=headers)
        cid = create_resp.json()["id"]

        # Complete it
        await client.patch(f"/commitments/{cid}", json={
            "status": "completed"
        }, headers=headers)

        # Try to cancel a completed commitment
        resp = await client.patch(f"/commitments/{cid}", json={
            "status": "cancelled"
        }, headers=headers)
        assert resp.status_code == 422

    async def test_update_commitment_not_found(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "notfound@example.com")
        resp = await client.patch(
            f"/commitments/{uuid.uuid4()}",
            json={"status": "completed"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404


class TestDeleteCommitment:
    async def test_delete_commitment_success(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "del_commit@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "To delete"
        }, headers=headers)
        cid = create_resp.json()["id"]

        resp = await client.delete(f"/commitments/{cid}", headers=headers)
        assert resp.status_code == 204

    async def test_delete_other_users_commitment(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "owner_del@example.com")
        headers = {"X-User-Id": user_id}
        create_resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Mine"
        }, headers=headers)
        cid = create_resp.json()["id"]

        # Another user tries to delete
        other_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/commitments/{cid}",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 404
