"""End-to-end tests for daily briefing endpoints."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestGetBriefing:
    """Tests for GET /briefing/{user_id}."""

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, client: AsyncClient) -> None:
        """Request without X-User-Id header returns 401."""
        user_id = str(uuid.uuid4())
        resp = await client.get(f"/briefing/{user_id}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_user_returns_403(self, client: AsyncClient) -> None:
        """Requesting another user's briefing returns 403."""
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        resp = await client.get(
            f"/briefing/{user_id}",
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_successful_briefing(self, client: AsyncClient) -> None:
        """Successful briefing generation returns structured response."""
        user_id = str(uuid.uuid4())

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=MagicMock(
            to_dict=lambda: {
                "agenda": [{"subject": "Standup"}],
                "pending_commitments": [],
                "overdue_commitments": [],
                "contextual_alerts": [],
                "briefing_text": "Your day looks clear.",
                "generated_at": "2025-03-10T07:00:00",
            }
        ))

        with patch("app.api.routers.briefing._get_generator", return_value=mock_generator):
            resp = await client.get(
                f"/briefing/{user_id}",
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "agenda" in data
        assert "pending_commitments" in data
        assert "overdue_commitments" in data
        assert "contextual_alerts" in data
        assert "briefing_text" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_briefing_response_schema(self, client: AsyncClient) -> None:
        """Briefing response matches expected schema types."""
        user_id = str(uuid.uuid4())

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=MagicMock(
            to_dict=lambda: {
                "agenda": [{"subject": "Meeting", "timestamp": "09:00"}],
                "pending_commitments": [{"commitment_text": "Review PR"}],
                "overdue_commitments": [{"commitment_text": "Old task"}],
                "contextual_alerts": ["Alert: meeting with Bob"],
                "briefing_text": "Busy day ahead.",
                "generated_at": "2025-03-10T07:00:00",
            }
        ))

        with patch("app.api.routers.briefing._get_generator", return_value=mock_generator):
            resp = await client.get(
                f"/briefing/{user_id}",
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["agenda"], list)
        assert isinstance(data["pending_commitments"], list)
        assert isinstance(data["overdue_commitments"], list)
        assert isinstance(data["contextual_alerts"], list)
        assert isinstance(data["briefing_text"], str)
        assert isinstance(data["generated_at"], str)

    @pytest.mark.asyncio
    async def test_briefing_claude_error_returns_502(self, client: AsyncClient) -> None:
        """When generator raises RuntimeError, return 502."""
        user_id = str(uuid.uuid4())

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("Claude API down"))

        with patch("app.api.routers.briefing._get_generator", return_value=mock_generator):
            resp = await client.get(
                f"/briefing/{user_id}",
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_invalid_user_id_format(self, client: AsyncClient) -> None:
        """Non-UUID user_id returns 422."""
        resp = await client.get(
            "/briefing/not-a-uuid",
            headers={"X-User-Id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422


class TestScheduleBriefing:
    """Tests for POST /briefing/{user_id}/schedule."""

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, client: AsyncClient) -> None:
        """Request without X-User-Id header returns 401."""
        user_id = str(uuid.uuid4())
        resp = await client.post(
            f"/briefing/{user_id}/schedule",
            json={"hour": 7, "minute": 0, "timezone": "UTC"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_user_returns_403(self, client: AsyncClient) -> None:
        """Scheduling for another user returns 403."""
        user_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        resp = await client.post(
            f"/briefing/{user_id}/schedule",
            json={"hour": 7, "minute": 0, "timezone": "UTC"},
            headers={"X-User-Id": other_id},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_schedule_success(self, client: AsyncClient) -> None:
        """Schedule briefing returns scheduled status."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.briefing._get_scheduler") as mock_get_sched:
            mock_sched = MagicMock()
            mock_get_sched.return_value = mock_sched
            mock_sched.is_available = True
            mock_sched.schedule_briefing = MagicMock(return_value=True)

            resp = await client.post(
                f"/briefing/{user_id}/schedule",
                json={"hour": 8, "minute": 30, "timezone": "America/New_York"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduled"] is True

    @pytest.mark.asyncio
    async def test_schedule_without_apscheduler(self, client: AsyncClient) -> None:
        """Schedule returns not-scheduled when APScheduler unavailable."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.briefing._get_scheduler") as mock_get_sched:
            mock_sched = MagicMock()
            mock_get_sched.return_value = mock_sched
            mock_sched.is_available = False
            mock_sched.schedule_briefing = MagicMock(return_value=False)

            resp = await client.post(
                f"/briefing/{user_id}/schedule",
                json={"hour": 7, "minute": 0, "timezone": "UTC"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduled"] is False

    @pytest.mark.asyncio
    async def test_schedule_invalid_hour(self, client: AsyncClient) -> None:
        """Invalid hour value returns 422."""
        user_id = str(uuid.uuid4())
        resp = await client.post(
            f"/briefing/{user_id}/schedule",
            json={"hour": 25, "minute": 0, "timezone": "UTC"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_schedule_invalid_minute(self, client: AsyncClient) -> None:
        """Invalid minute value returns 422."""
        user_id = str(uuid.uuid4())
        resp = await client.post(
            f"/briefing/{user_id}/schedule",
            json={"hour": 7, "minute": 61, "timezone": "UTC"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_schedule_default_values(self, client: AsyncClient) -> None:
        """Schedule with default values (hour=7, minute=0)."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.briefing._get_scheduler") as mock_get_sched:
            mock_sched = MagicMock()
            mock_get_sched.return_value = mock_sched
            mock_sched.is_available = True
            mock_sched.schedule_briefing = MagicMock(return_value=True)

            resp = await client.post(
                f"/briefing/{user_id}/schedule",
                json={},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
