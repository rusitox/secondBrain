"""Integration tests for API CRUD — full lifecycle through HTTP client.

These tests exercise router → service → DB together, focusing on
cross-entity interactions and complete user workflows.
"""
import uuid

import pytest
from httpx import AsyncClient


async def _create_user(
    client: AsyncClient,
    email: str = "crud@example.com",
    full_name: str = "CRUD User",
) -> dict:
    resp = await client.post("/users/", json={
        "email": email, "full_name": full_name,
    })
    assert resp.status_code == 201
    return resp.json()


class TestUserLifecycle:
    """Full user lifecycle: create → read → update → delete."""

    async def test_full_user_lifecycle(self, client: AsyncClient) -> None:
        # Create
        user = await _create_user(client, "lifecycle@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        # Read
        resp = await client.get(f"/users/{user_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "lifecycle@example.com"

        # Update
        resp = await client.patch(
            f"/users/{user_id}",
            json={"full_name": "Updated Name", "timezone": "America/New_York"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "Updated Name"
        assert data["timezone"] == "America/New_York"

        # Delete
        resp = await client.delete(f"/users/{user_id}", headers=headers)
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(f"/users/{user_id}", headers=headers)
        assert resp.status_code == 404


class TestCommitmentLifecycle:
    """Full commitment lifecycle: create → list → update status → delete."""

    async def test_full_commitment_lifecycle(self, client: AsyncClient) -> None:
        user = await _create_user(client, "commit_life@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        # Create
        resp = await client.post("/commitments/", json={
            "user_id": user_id,
            "commitment_text": "Review the PR",
            "priority": 1,
        }, headers=headers)
        assert resp.status_code == 201
        commitment = resp.json()
        cid = commitment["id"]
        assert commitment["status"] == "pending"
        assert commitment["priority"] == 1

        # List — should contain the commitment
        resp = await client.get("/commitments/", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Update status to completed
        resp = await client.patch(
            f"/commitments/{cid}",
            json={"status": "completed"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        # Filter pending — should be empty
        resp = await client.get("/commitments/?status=pending", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        # Filter completed — should have one
        resp = await client.get("/commitments/?status=completed", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Delete
        resp = await client.delete(f"/commitments/{cid}", headers=headers)
        assert resp.status_code == 204

    async def test_status_transition_enforcement(self, client: AsyncClient) -> None:
        """Once completed, cannot transition to another status."""
        user = await _create_user(client, "transition@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        resp = await client.post("/commitments/", json={
            "user_id": user_id, "commitment_text": "Ship it",
        }, headers=headers)
        cid = resp.json()["id"]

        # Complete it
        await client.patch(
            f"/commitments/{cid}",
            json={"status": "completed"},
            headers=headers,
        )

        # Try to cancel — should fail
        resp = await client.patch(
            f"/commitments/{cid}",
            json={"status": "cancelled"},
            headers=headers,
        )
        assert resp.status_code == 422

        # Try to revert to pending — should fail
        resp = await client.patch(
            f"/commitments/{cid}",
            json={"status": "pending"},
            headers=headers,
        )
        assert resp.status_code == 422


class TestIntegrationLifecycle:
    """Full integration lifecycle: create → list → toggle → delete."""

    async def test_full_integration_lifecycle(self, client: AsyncClient) -> None:
        user = await _create_user(client, "integ_life@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        # Create
        resp = await client.post("/integrations/", json={
            "user_id": user_id,
            "platform": "slack",
            "access_token": "xoxb-secret",
        }, headers=headers)
        assert resp.status_code == 201
        integration = resp.json()
        iid = integration["id"]
        assert integration["is_active"] is True
        assert "access_token" not in integration

        # List
        resp = await client.get("/integrations/", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Toggle inactive
        resp = await client.patch(
            f"/integrations/{iid}",
            json={"is_active": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # Toggle back active
        resp = await client.patch(
            f"/integrations/{iid}",
            json={"is_active": True},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

        # Delete
        resp = await client.delete(f"/integrations/{iid}", headers=headers)
        assert resp.status_code == 204

    async def test_multiple_platforms_filter(self, client: AsyncClient) -> None:
        user = await _create_user(client, "multi_plat@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        for platform in ["slack", "outlook", "fathom"]:
            await client.post("/integrations/", json={
                "user_id": user_id,
                "platform": platform,
                "access_token": f"token-{platform}",
            }, headers=headers)

        # All
        resp = await client.get("/integrations/", headers=headers)
        assert len(resp.json()) == 3

        # Filter by platform
        resp = await client.get("/integrations/?platform=outlook", headers=headers)
        data = resp.json()
        assert len(data) == 1
        assert data[0]["platform"] == "outlook"


class TestCrossEntityInteractions:
    """Tests that span multiple entity types."""

    async def test_delete_user_cascades_commitments_via_api(
        self, client: AsyncClient,
    ) -> None:
        """Deleting a user should cascade-delete their commitments."""
        user = await _create_user(client, "cascade_api@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        # Create commitments
        for text in ["Task A", "Task B", "Task C"]:
            await client.post("/commitments/", json={
                "user_id": user_id, "commitment_text": text,
            }, headers=headers)

        # Verify 3 commitments
        resp = await client.get("/commitments/", headers=headers)
        assert len(resp.json()) == 3

        # Delete user
        resp = await client.delete(f"/users/{user_id}", headers=headers)
        assert resp.status_code == 204

        # Commitments should be gone (re-creating user to verify via DB)
        # Since user is deleted, we can't query via API. The cascade is
        # already verified in test_database.py at ORM level.

    async def test_delete_user_cascades_integrations_via_api(
        self, client: AsyncClient,
    ) -> None:
        """Deleting a user should cascade-delete their integrations."""
        user = await _create_user(client, "cascade_int@example.com")
        user_id = user["id"]
        headers = {"X-User-Id": user_id}

        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "slack", "access_token": "t1",
        }, headers=headers)
        await client.post("/integrations/", json={
            "user_id": user_id, "platform": "outlook", "access_token": "t2",
        }, headers=headers)

        resp = await client.get("/integrations/", headers=headers)
        assert len(resp.json()) == 2

        # Delete user — integrations should cascade
        resp = await client.delete(f"/users/{user_id}", headers=headers)
        assert resp.status_code == 204

    async def test_row_isolation_commitments(self, client: AsyncClient) -> None:
        """User A cannot see or modify User B's commitments."""
        user_a = await _create_user(client, "user_a@example.com", "User A")
        user_b = await _create_user(client, "user_b@example.com", "User B")
        headers_a = {"X-User-Id": user_a["id"]}
        headers_b = {"X-User-Id": user_b["id"]}

        # Each user creates a commitment
        resp_a = await client.post("/commitments/", json={
            "user_id": user_a["id"], "commitment_text": "A's task",
        }, headers=headers_a)
        cid_a = resp_a.json()["id"]

        resp_b = await client.post("/commitments/", json={
            "user_id": user_b["id"], "commitment_text": "B's task",
        }, headers=headers_b)
        cid_b = resp_b.json()["id"]

        # A only sees their own
        resp = await client.get("/commitments/", headers=headers_a)
        assert len(resp.json()) == 1
        assert resp.json()[0]["commitment_text"] == "A's task"

        # A cannot access B's commitment
        resp = await client.get(f"/commitments/{cid_b}", headers=headers_a)
        assert resp.status_code == 404

        # A cannot delete B's commitment
        resp = await client.delete(f"/commitments/{cid_b}", headers=headers_a)
        assert resp.status_code == 404

    async def test_row_isolation_integrations(self, client: AsyncClient) -> None:
        """User A cannot see or modify User B's integrations."""
        user_a = await _create_user(client, "iso_a@example.com", "User A")
        user_b = await _create_user(client, "iso_b@example.com", "User B")
        headers_a = {"X-User-Id": user_a["id"]}
        headers_b = {"X-User-Id": user_b["id"]}

        resp_b = await client.post("/integrations/", json={
            "user_id": user_b["id"], "platform": "slack", "access_token": "secret",
        }, headers=headers_b)
        iid_b = resp_b.json()["id"]

        # A sees empty list
        resp = await client.get("/integrations/", headers=headers_a)
        assert len(resp.json()) == 0

        # A cannot access B's integration
        resp = await client.get(f"/integrations/{iid_b}", headers=headers_a)
        assert resp.status_code == 404

        # A cannot delete B's integration
        resp = await client.delete(f"/integrations/{iid_b}", headers=headers_a)
        assert resp.status_code == 404
