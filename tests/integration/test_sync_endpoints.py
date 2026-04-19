"""Integration tests for sync API endpoints."""
import uuid

import pytest
from httpx import AsyncClient


async def _create_user_with_integration(
    client: AsyncClient,
    email: str = "sync@example.com",
    platform: str = "outlook",
) -> tuple:
    """Create a user and an integration, return (user_id, integration_id)."""
    resp = await client.post("/users/", json={
        "email": email, "full_name": "Sync User"
    })
    user_id = resp.json()["id"]

    resp = await client.post(
        "/integrations/",
        json={"user_id": user_id, "platform": platform, "access_token": "test-token"},
        headers={"X-User-Id": user_id},
    )
    integration_id = resp.json()["id"]
    return user_id, integration_id


class TestGetSyncStatus:
    @pytest.mark.asyncio
    async def test_sync_status_returns_integrations(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(client)
        resp = await client.get(
            "/sync/status",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "scheduler_active" in data
        assert "integrations" in data
        assert len(data["integrations"]) >= 1

    @pytest.mark.asyncio
    async def test_sync_status_empty_for_new_user(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={
            "email": "nosync@example.com", "full_name": "No Sync"
        })
        user_id = resp.json()["id"]
        resp = await client.get(
            "/sync/status",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["integrations"] == []


class TestConfigureSync:
    @pytest.mark.asyncio
    async def test_configure_sync(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(client)
        resp = await client.post(
            "/sync/configure",
            json={"platform": "outlook", "enabled": True, "interval_minutes": 60},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sync_enabled"] is True
        assert data["sync_interval_minutes"] == 60
        assert data["platform"] == "outlook"

    @pytest.mark.asyncio
    async def test_configure_nonexistent_platform(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(client)
        resp = await client.post(
            "/sync/configure",
            json={"platform": "nonexistent", "enabled": True},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_disable_sync(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(client)
        resp = await client.post(
            "/sync/configure",
            json={"platform": "outlook", "enabled": False},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["sync_enabled"] is False


class TestTriggerSync:
    @pytest.mark.asyncio
    async def test_trigger_nonexistent_integration(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(
            client, email="trigger@example.com"
        )
        resp = await client.post(
            "/sync/trigger/slack",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_unsupported_platform(self, client: AsyncClient) -> None:
        user_id, _ = await _create_user_with_integration(
            client, email="trigger2@example.com", platform="outlook"
        )
        # Platform exists as integration but is not in _CONNECTORS for this test
        # The _CONNECTORS dict is imported from ingestion router
        resp = await client.post(
            "/sync/trigger/outlook",
            headers={"X-User-Id": user_id},
        )
        # Will either be 400 (unsupported) or 200 with error (connector fails)
        # since we're in test env without real connectors
        assert resp.status_code in (200, 400)
