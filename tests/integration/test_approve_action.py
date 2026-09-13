"""Integration tests for POST /interactions/actions/{id}/approve — the
execute side of the action gate. The registered NotionPublishExecutor is
swapped for a fake via app.api.routers.interactions.get_executor so these
tests never call NotionPublisher/httpx; app/services/actions/executors/
tests would cover the real Notion wiring separately if/when that gets its
own coverage.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposed_action import ProposedAction
from app.services.actions.executors.notion import NotionPublishPayload


async def _create_user_and_api_key(client: AsyncClient) -> tuple:
    resp = await client.post("/users/", json={
        "email": f"approve_{uuid.uuid4().hex[:8]}@test.com",
        "full_name": "Approve Test User",
    })
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    resp = await client.post(
        "/auth/api-keys", json={"name": "test-key"}, headers={"X-User-Id": user_id},
    )
    assert resp.status_code == 201, resp.text
    api_key = resp.json()["key"]
    return user_id, api_key, {"Authorization": f"Bearer {api_key}"}


def _payload_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _create_proposed_action(db: AsyncSession, user_id: str) -> ProposedAction:
    payload = {"kind": "briefing", "text": "Resumen", "date_str": "2026-09-09"}
    action = ProposedAction(
        user_id=uuid.UUID(user_id),
        session_id=uuid.uuid4(),
        action_type="notion_publish",
        payload=payload,
        payload_sha256=_payload_hash(payload),
        artifact={"kind": "key_values", "title": "Publicar", "rows": [{"label": "x", "value": "y"}]},
        risk="low",
        idempotency_key=f"notion_publish:{_payload_hash(payload)}",
        executor_version="1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(action)
    await db.commit()
    return action


class _FakeExecutor:
    action_type = "notion_publish"
    version = "1"
    payload_model = NotionPublishPayload
    risk = "low"

    def __init__(self, result: Any = None, exc: Any = None) -> None:
        self._result = result if result is not None else {"page_id": "page-123"}
        self._exc = exc

    async def execute(self, db: Any, user_id: Any, payload: Any) -> Dict[str, Any]:
        if self._exc is not None:
            raise self._exc
        return self._result


class TestGetProposedAction:
    """GET /interactions/actions/{id} — the client's only way to fetch a
    proposed action's artifact/payload_sha256, since the action_proposed
    SSE event only ever carries the bare id."""

    @pytest.mark.asyncio
    async def test_returns_artifact_and_payload_hash(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _api_key, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        resp = await client.get(f"/interactions/actions/{action.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(action.id)
        assert data["action_type"] == "notion_publish"
        assert data["status"] == "proposed"
        assert data["risk"] == "low"
        assert data["artifact"]["kind"] == "key_values"
        assert data["payload_sha256"] == action.payload_sha256

    @pytest.mark.asyncio
    async def test_unknown_action_returns_404(self, client: AsyncClient) -> None:
        _user_id, _api_key, headers = await _create_user_and_api_key(client)
        resp = await client.get(f"/interactions/actions/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_user_action_returns_404(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        owner_id, _owner_key, _owner_headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, owner_id)
        _other_id, _other_key, other_headers = await _create_user_and_api_key(client)

        resp = await client.get(f"/interactions/actions/{action.id}", headers=other_headers)
        assert resp.status_code == 404


class TestApproveActionHappyPath:
    @pytest.mark.asyncio
    async def test_approve_executes_and_marks_row_executed(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        with patch("app.api.routers.interactions.get_executor", return_value=_FakeExecutor()):
            resp = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "executed"
        assert body["result"]["page_id"] == "page-123"

        row = (await db_session.execute(
            text("SELECT status, result, executed_at FROM proposed_actions WHERE id = :id"),
            {"id": action.id.hex},
        )).first()
        assert row is not None
        assert row[0] == "executed"
        assert "page-123" in row[1]
        assert row[2] is not None

        audit_events = [
            r[0] for r in (await db_session.execute(
                text("SELECT event FROM action_audit_log WHERE action_id = :id ORDER BY created_at"),
                {"id": action.id.hex},
            )).all()
        ]
        assert audit_events == ["approved", "executed"]


class TestApproveActionValidation:
    @pytest.mark.asyncio
    async def test_unknown_action_returns_404(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        resp = await client.post(
            f"/interactions/actions/{uuid.uuid4()}/approve",
            json={"payload_sha256": "x" * 64},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_user_action_returns_404(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        owner_id, _, _ = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, owner_id)
        _, _, other_headers = await _create_user_and_api_key(client)

        resp = await client.post(
            f"/interactions/actions/{action.id}/approve",
            json={"payload_sha256": action.payload_sha256},
            headers=other_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_hash_mismatch_returns_409(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        resp = await client.post(
            f"/interactions/actions/{action.id}/approve",
            json={"payload_sha256": "0" * 64},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_double_approve_returns_409(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        with patch("app.api.routers.interactions.get_executor", return_value=_FakeExecutor()):
            first = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )
            assert first.status_code == 200

            second = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )
        assert second.status_code == 409

    @pytest.mark.asyncio
    async def test_unregistered_action_type_returns_409(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        with patch("app.api.routers.interactions.get_executor", return_value=None):
            resp = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )
        assert resp.status_code == 409


class TestApproveActionExecutionFailure:
    @pytest.mark.asyncio
    async def test_executor_error_result_marks_action_failed(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        with patch(
            "app.api.routers.interactions.get_executor",
            return_value=_FakeExecutor(result={"error": "Notion workspace not configured"}),
        ):
            resp = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )

        assert resp.status_code == 502
        row = (await db_session.execute(
            text("SELECT status, error FROM proposed_actions WHERE id = :id"), {"id": action.id.hex},
        )).first()
        assert row is not None
        assert row[0] == "failed"
        assert "not configured" in row[1]

    @pytest.mark.asyncio
    async def test_executor_exception_marks_action_failed(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        action = await _create_proposed_action(db_session, user_id)

        with patch(
            "app.api.routers.interactions.get_executor",
            return_value=_FakeExecutor(exc=RuntimeError("boom")),
        ):
            resp = await client.post(
                f"/interactions/actions/{action.id}/approve",
                json={"payload_sha256": action.payload_sha256},
                headers=headers,
            )

        assert resp.status_code == 502
        row = (await db_session.execute(
            text("SELECT status FROM proposed_actions WHERE id = :id"), {"id": action.id.hex},
        )).first()
        assert row is not None
        assert row[0] == "failed"
