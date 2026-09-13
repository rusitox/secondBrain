"""Integration tests for GET /systems/status — the MAREA header's
connected-systems semaphore (app/api/routers/systems.py). Covers the
health rules (ok/stale/error/disabled/external) and, per Mariano's
explicit requirement, that the source list is never hardcoded: it must
reflect whatever the user has actually connected or has document backlog
for, nothing more and nothing less.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Platform
from tests.factories import make_document, make_integration, make_user


async def _create_user(client: AsyncClient, email: str) -> str:
    resp = await client.post("/users/", json={"email": email, "full_name": "Systems User"})
    return resp.json()["id"]


class TestSystemsStatusEmpty:
    @pytest.mark.asyncio
    async def test_no_integrations_and_no_documents_returns_empty_list(
        self, client: AsyncClient,
    ) -> None:
        user_id = await _create_user(client, "systems_empty@example.com")
        resp = await client.get("/systems/status", headers={"X-User-Id": user_id})
        assert resp.status_code == 200
        assert resp.json()["systems"] == []


class TestSystemsStatusHealthRules:
    @pytest.mark.asyncio
    async def test_recently_synced_enabled_integration_is_ok(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"ok_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.OUTLOOK)
        integ.last_sync_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        integ.last_sync_status = "success"
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        assert resp.status_code == 200
        systems = resp.json()["systems"]
        assert len(systems) == 1
        assert systems[0]["source"] == "outlook"
        assert systems[0]["health"] == "ok"
        assert systems[0]["detail"] is None

    @pytest.mark.asyncio
    async def test_error_last_sync_status_surfaces_as_error_with_detail(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"err_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.SLACK)
        integ.last_sync_at = datetime.now(timezone.utc)
        integ.last_sync_status = "error"
        integ.last_sync_error = "401 Unauthorized"
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["health"] == "error"
        assert systems[0]["detail"] == "401 Unauthorized"

    @pytest.mark.asyncio
    async def test_disabled_integration_is_disabled_not_error(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"dis_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.TEAMS)
        integ.sync_enabled = False
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["health"] == "disabled"

    @pytest.mark.asyncio
    async def test_never_synced_enabled_integration_is_stale(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"never_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.OUTLOOK)
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["health"] == "stale"

    @pytest.mark.asyncio
    async def test_sync_older_than_interval_multiple_is_stale(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"old_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.OUTLOOK)
        integ.sync_interval_minutes = 30
        integ.last_sync_status = "success"
        # Well past 2x the 30-minute interval and past the 60-minute floor.
        integ.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["health"] == "stale"

    @pytest.mark.asyncio
    async def test_fathom_is_always_external_even_with_a_stray_error_status(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """Fathom's own sync is script-driven, out of band — a manual
        /sync/trigger/fathom call hitting its NotImplementedError must
        never make the header semaphore cry wolf."""
        user = make_user(email=f"fathom_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.FATHOM)
        integ.last_sync_status = "error"
        integ.last_sync_error = "NotImplementedError: Fathom has no public REST API"
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["source"] == "fathom"
        assert systems[0]["health"] == "external"
        assert "error" not in (systems[0]["detail"] or "").lower()


class TestSystemsStatusDynamicSourceList:
    @pytest.mark.asyncio
    async def test_high_backlog_downgrades_an_otherwise_ok_source_to_stale(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"backlog_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        integ = make_integration(user_id=user.id, platform=Platform.SLACK)
        integ.last_sync_status = "success"
        integ.last_sync_at = datetime.now(timezone.utc)
        db_session.add(integ)
        for i in range(201):
            db_session.add(make_document(user_id=user.id, source="slack", source_id=f"doc-{i}"))
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["health"] == "stale"
        assert systems[0]["pending_documents"] == 201

    @pytest.mark.asyncio
    async def test_high_backlog_on_a_connector_less_source_is_also_stale(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """Regression: the backlog-downgrade rule used to only apply to
        sources with an active Integration row — a source that exists
        purely via document backlog (no Integration at all, e.g. the I+D
        agent) stayed hardcoded "ok" no matter how large its backlog."""
        user = make_user(email=f"rd_backlog_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        for i in range(201):
            db_session.add(make_document(user_id=user.id, source="rd", source_id=f"doc-{i}"))
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert systems[0]["source"] == "rd"
        assert systems[0]["health"] == "stale"
        assert systems[0]["pending_documents"] == 201

    @pytest.mark.asyncio
    async def test_source_with_backlog_but_no_integration_row_still_appears(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """The I+D/R&D agent's MCP-backed source was never a connector with
        its own Integration row — it must still show up here, since
        Mariano's requirement is "whatever is real and dynamic", not
        "whatever has an Integration row"."""
        user = make_user(email=f"rd_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        db_session.add(make_document(user_id=user.id, source="rd", source_id="doc-1"))
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert len(systems) == 1
        assert systems[0]["source"] == "rd"
        assert systems[0]["sync_enabled"] is False
        assert systems[0]["pending_documents"] == 1

    @pytest.mark.asyncio
    async def test_source_list_grows_the_moment_a_new_integration_is_added(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """No hardcoded platform list anywhere in the response — connecting
        a second, previously-absent source must make it appear on its own."""
        user = make_user(email=f"grow_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        assert resp.json()["systems"] == []

        integ = make_integration(user_id=user.id, platform=Platform.NOTION)
        db_session.add(integ)
        await db_session.commit()

        resp = await client.get("/systems/status", headers={"X-User-Id": str(user.id)})
        systems = resp.json()["systems"]
        assert len(systems) == 1
        assert systems[0]["source"] == "notion"


class TestSystemsStatusSchedulerFlags:
    @pytest.mark.asyncio
    async def test_response_always_includes_scheduler_flags(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "scheduler_flags@example.com")
        resp = await client.get("/systems/status", headers={"X-User-Id": user_id})
        data = resp.json()
        assert "sync_scheduler_active" in data
        assert "knowledge_scheduler_active" in data
