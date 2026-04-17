"""Integration tests for identity CRUD and stats endpoints."""
import uuid

import pytest
from httpx import AsyncClient


class TestIdentityEndpoints:
    """Tests for POST/GET/PATCH /users/{user_id}/identity."""

    @pytest.mark.asyncio
    async def test_create_identity(self, client: AsyncClient) -> None:
        """Create a user then create their identity."""
        # Create user first
        user_resp = await client.post("/users/", json={
            "email": f"id-test-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "Identity Test",
        })
        assert user_resp.status_code == 201
        user_id = user_resp.json()["id"]

        # Create identity
        resp = await client.post(
            f"/users/{user_id}/identity",
            json={
                "persona_description": "CTO at startup",
                "tone_guidelines": "Direct and action-oriented",
                "heuristics": {"urgent_means_sameday": True},
            },
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["persona_description"] == "CTO at startup"
        assert data["tone_guidelines"] == "Direct and action-oriented"
        assert data["heuristics"]["urgent_means_sameday"] is True
        assert data["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_get_identity(self, client: AsyncClient) -> None:
        """Get an existing identity."""
        user_resp = await client.post("/users/", json={
            "email": f"id-get-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "Get Test",
        })
        user_id = user_resp.json()["id"]

        # Create
        await client.post(
            f"/users/{user_id}/identity",
            json={"persona_description": "Engineer"},
            headers={"X-User-Id": user_id},
        )

        # Get
        resp = await client.get(
            f"/users/{user_id}/identity",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["persona_description"] == "Engineer"

    @pytest.mark.asyncio
    async def test_get_identity_not_found(self, client: AsyncClient) -> None:
        """Get identity for user without one returns 404."""
        user_resp = await client.post("/users/", json={
            "email": f"id-nf-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "No Identity",
        })
        user_id = user_resp.json()["id"]

        resp = await client.get(
            f"/users/{user_id}/identity",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_identity(self, client: AsyncClient) -> None:
        """Update an existing identity."""
        user_resp = await client.post("/users/", json={
            "email": f"id-up-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "Update Test",
        })
        user_id = user_resp.json()["id"]

        # Create
        await client.post(
            f"/users/{user_id}/identity",
            json={"persona_description": "Old role", "tone_guidelines": "Formal"},
            headers={"X-User-Id": user_id},
        )

        # Update only tone
        resp = await client.patch(
            f"/users/{user_id}/identity",
            json={"tone_guidelines": "Casual and friendly"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona_description"] == "Old role"  # unchanged
        assert data["tone_guidelines"] == "Casual and friendly"

    @pytest.mark.asyncio
    async def test_create_duplicate_identity_returns_409(self, client: AsyncClient) -> None:
        """Creating a second identity for the same user returns 409."""
        user_resp = await client.post("/users/", json={
            "email": f"id-dup-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "Dup Test",
        })
        user_id = user_resp.json()["id"]

        # Create first
        resp1 = await client.post(
            f"/users/{user_id}/identity",
            json={"persona_description": "First"},
            headers={"X-User-Id": user_id},
        )
        assert resp1.status_code == 201

        # Create second → 409
        resp2 = await client.post(
            f"/users/{user_id}/identity",
            json={"persona_description": "Second"},
            headers={"X-User-Id": user_id},
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_identity_auth_403(self, client: AsyncClient) -> None:
        """Accessing another user's identity returns 403."""
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        resp = await client.get(
            f"/users/{user_id}/identity",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_identity_no_auth_401(self, client: AsyncClient) -> None:
        """Missing auth header returns 401."""
        user_id = str(uuid.uuid4())
        resp = await client.get(f"/users/{user_id}/identity")
        assert resp.status_code == 401


class TestStatsEndpoint:
    """Tests for GET /users/{user_id}/stats."""

    @pytest.mark.asyncio
    async def test_stats_empty_user(self, client: AsyncClient) -> None:
        """Stats for user with no data returns zeros."""
        user_resp = await client.post("/users/", json={
            "email": f"stats-{uuid.uuid4().hex[:8]}@test.com",
            "full_name": "Stats Test",
        })
        user_id = user_resp.json()["id"]

        resp = await client.get(
            f"/users/{user_id}/stats",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents_total"] == 0
        assert data["commitments_pending"] == 0
        assert data["commitments_overdue"] == 0
        assert data["integrations_active"] == 0
        assert data["integrations_total"] == 0
        assert data["last_sync"] is None

    @pytest.mark.asyncio
    async def test_stats_auth_403(self, client: AsyncClient) -> None:
        """Accessing another user's stats returns 403."""
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        resp = await client.get(
            f"/users/{user_id}/stats",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stats_no_auth_401(self, client: AsyncClient) -> None:
        """Missing auth returns 401."""
        resp = await client.get(f"/users/{str(uuid.uuid4())}/stats")
        assert resp.status_code == 401
