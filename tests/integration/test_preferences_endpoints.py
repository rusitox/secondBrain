"""Integration tests for /users/me preferences, onboarding, and Notion config endpoints."""
import pytest
from httpx import AsyncClient


async def _create_user(client: AsyncClient, email: str = "prefs@example.com") -> str:
    """Create a user and return user_id."""
    resp = await client.post("/users/", json={
        "email": email, "full_name": "Prefs User",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


class TestGetPreferences:
    @pytest.mark.asyncio
    async def test_get_preferences_default(self, client: AsyncClient) -> None:
        user_id = await _create_user(client)
        resp = await client.get(
            "/users/me/preferences",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"] == {}
        assert data["onboarding"]["step"] == 0
        assert data["onboarding"]["completed"] is False
        assert data["notion_config"] is None

    @pytest.mark.asyncio
    async def test_get_preferences_after_update(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="prefs2@example.com")
        # Update preferences
        await client.patch(
            "/users/me/preferences",
            json={"preferences": {"briefing_hour": 8, "alert_mode": "immediate"}},
            headers={"X-User-Id": user_id},
        )
        resp = await client.get(
            "/users/me/preferences",
            headers={"X-User-Id": user_id},
        )
        data = resp.json()
        assert data["preferences"]["briefing_hour"] == 8
        assert data["preferences"]["alert_mode"] == "immediate"


class TestUpdatePreferences:
    @pytest.mark.asyncio
    async def test_merge_preferences(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="merge@example.com")
        # Set initial
        await client.patch(
            "/users/me/preferences",
            json={"preferences": {"key1": "val1", "key2": "val2"}},
            headers={"X-User-Id": user_id},
        )
        # Merge new key, overwrite existing
        resp = await client.patch(
            "/users/me/preferences",
            json={"preferences": {"key2": "updated", "key3": "val3"}},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["key1"] == "val1"
        assert prefs["key2"] == "updated"
        assert prefs["key3"] == "val3"


class TestOnboarding:
    @pytest.mark.asyncio
    async def test_get_onboarding_default(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="onb@example.com")
        resp = await client.get(
            "/users/me/onboarding",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json() == {"step": 0, "completed": False}

    @pytest.mark.asyncio
    async def test_update_onboarding_step(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="onb2@example.com")
        resp = await client.patch(
            "/users/me/onboarding",
            json={"step": 3},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["step"] == 3
        assert resp.json()["completed"] is False

    @pytest.mark.asyncio
    async def test_complete_onboarding(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="onb3@example.com")
        resp = await client.patch(
            "/users/me/onboarding",
            json={"step": 5, "completed": True},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["step"] == 5
        assert resp.json()["completed"] is True

    @pytest.mark.asyncio
    async def test_partial_update_keeps_existing(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="onb4@example.com")
        # Set step
        await client.patch(
            "/users/me/onboarding",
            json={"step": 2},
            headers={"X-User-Id": user_id},
        )
        # Update only completed, step should remain 2
        resp = await client.patch(
            "/users/me/onboarding",
            json={"completed": True},
            headers={"X-User-Id": user_id},
        )
        assert resp.json()["step"] == 2
        assert resp.json()["completed"] is True


class TestNotionConfig:
    @pytest.mark.asyncio
    async def test_get_notion_config_default(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="notion@example.com")
        resp = await client.get(
            "/users/me/notion-config",
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["config"] is None

    @pytest.mark.asyncio
    async def test_set_notion_config(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="notion2@example.com")
        config = {
            "enabled": True,
            "root_page_id": "abc123",
            "commitments_db_id": "def456",
        }
        resp = await client.put(
            "/users/me/notion-config",
            json={"config": config},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["enabled"] is True
        assert resp.json()["config"]["root_page_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_clear_notion_config(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="notion3@example.com")
        # Set config
        await client.put(
            "/users/me/notion-config",
            json={"config": {"enabled": True}},
            headers={"X-User-Id": user_id},
        )
        # Clear config
        resp = await client.put(
            "/users/me/notion-config",
            json={"config": None},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["config"] is None

    @pytest.mark.asyncio
    async def test_notion_config_visible_in_preferences(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, email="notion4@example.com")
        config = {"enabled": True, "read_mode": "full"}
        await client.put(
            "/users/me/notion-config",
            json={"config": config},
            headers={"X-User-Id": user_id},
        )
        resp = await client.get(
            "/users/me/preferences",
            headers={"X-User-Id": user_id},
        )
        assert resp.json()["notion_config"]["enabled"] is True
