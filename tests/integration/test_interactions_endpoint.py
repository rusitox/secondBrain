"""Integration tests for POST /interactions/{id}/answer.

LLM/Strands calls are mocked (via _get_agent) — these tests do NOT hit
OpenAI/Anthropic or construct a real strands.Agent. See
tests/integration/test_interrupt_resume.py for orchestrator-level coverage
of the actual snapshot/interrupt mechanics this endpoint sits on top of.
"""
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent import interactions_store


async def _create_user_and_api_key(client: AsyncClient) -> tuple:
    resp = await client.post("/users/", json={
        "email": f"interact_{uuid.uuid4().hex[:8]}@test.com",
        "full_name": "Interactions Test User",
    })
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    resp = await client.post(
        "/auth/api-keys",
        json={"name": "test-key"},
        headers={"X-User-Id": user_id},
    )
    assert resp.status_code == 201, resp.text
    api_key = resp.json()["key"]
    return user_id, api_key, {"Authorization": f"Bearer {api_key}"}


_SPEC = {
    "version": "1",
    "request_id": "r1",
    "kicker": "needs_datum",
    "prompt": [{"text": "¿Qué decidís?", "emphasis": "none"}],
    "fields": [
        {
            "key": "decision", "kind": "single_select", "label": "Decisión", "required": True,
            "options": [{"id": "approve", "label": "Aprobar"}, {"id": "reject", "label": "Rechazar"}],
            "default": "approve",
        },
        {"key": "comment", "kind": "text", "label": "Comentario", "required": False},
    ],
    "submit_label": "Confirmar",
    "allow_dismiss": True,
}


async def _open_interaction(db: AsyncSession, user_id: str):
    interaction = await interactions_store.create_interaction(
        db, uuid.UUID(user_id), uuid.uuid4(), None, f"int-{uuid.uuid4().hex[:8]}", "tu_1", dict(_SPEC),
    )
    await db.commit()
    return interaction


class TestGetInteraction:
    """GET /interactions/{id} — the client's only way to learn what an
    interaction actually asks, since done.awaiting only ever carries ids."""

    @pytest.mark.asyncio
    async def test_returns_spec_for_open_interaction(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _api_key, headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, user_id)

        resp = await client.get(f"/interactions/{interaction.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(interaction.id)
        assert data["status"] == "open"
        assert data["spec"]["kicker"] == "needs_datum"
        assert data["spec"]["fields"][0]["key"] == "decision"
        assert data["answer"] is None

    @pytest.mark.asyncio
    async def test_returns_answer_for_answered_interaction(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _api_key, headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, user_id)
        await interactions_store.claim_interaction_for_answer(
            db_session, uuid.UUID(user_id), interaction.id, {"decision": "approve"}, "ui",
        )
        await db_session.commit()

        resp = await client.get(f"/interactions/{interaction.id}", headers=headers)
        data = resp.json()
        assert data["status"] == "answered"
        assert data["answer"] == {"decision": "approve"}

    @pytest.mark.asyncio
    async def test_unknown_interaction_returns_404(self, client: AsyncClient) -> None:
        _user_id, _api_key, headers = await _create_user_and_api_key(client)
        resp = await client.get(f"/interactions/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_user_interaction_returns_404(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        owner_id, _owner_key, _owner_headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, owner_id)
        _other_id, _other_key, other_headers = await _create_user_and_api_key(client)

        resp = await client.get(f"/interactions/{interaction.id}", headers=other_headers)
        assert resp.status_code == 404


class TestAnswerInteractionValidation:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(f"/interactions/{uuid.uuid4()}/answer", json={"answer": {}})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_interaction_returns_404(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        resp = await client.post(
            f"/interactions/{uuid.uuid4()}/answer",
            json={"answer": {"decision": "approve"}},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_422(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, user_id)

        resp = await client.post(
            f"/interactions/{interaction.id}/answer",
            json={"answer": {"comment": "sin decisión"}},  # missing required "decision"
            headers=headers,
        )
        assert resp.status_code == 422

        # Rejecting for a missing field must not burn the interaction — it
        # should still be answerable with a complete payload.
        reloaded = await interactions_store.get_interaction(db_session, uuid.UUID(user_id), interaction.id)
        assert reloaded is not None
        assert reloaded.status.value == "open"

    @pytest.mark.asyncio
    async def test_already_answered_interaction_returns_409(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, user_id)
        await interactions_store.claim_interaction_for_answer(
            db_session, uuid.UUID(user_id), interaction.id, {"decision": "approve"}, "ui",
        )
        await db_session.commit()

        resp = await client.post(
            f"/interactions/{interaction.id}/answer",
            json={"answer": {"decision": "approve"}},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cross_user_interaction_returns_404(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """A user must never learn (even via a 409 vs 404 distinction)
        whether an interaction id belonging to someone else exists."""
        owner_id, _, _ = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, owner_id)
        _, _, other_headers = await _create_user_and_api_key(client)

        resp = await client.post(
            f"/interactions/{interaction.id}/answer",
            json={"answer": {"decision": "approve"}},
            headers=other_headers,
        )
        assert resp.status_code == 404


def _make_stream_orchestrator(events: list, result: Dict[str, Any]) -> MagicMock:
    async def fake_resume(*, db, user_id, session_id, interrupt_id, answer_values, emit=None):
        if emit is not None:
            for event_name, event_data in events:
                emit(event_name, event_data)
        return result

    orch = MagicMock()
    orch.resume = fake_resume
    return orch


class TestAnswerInteractionResume:
    @pytest.fixture(autouse=True)
    def _reset_sse_starlette_app_status(self):
        """See tests/integration/test_agent_endpoint.py's identical fixture —
        sse_starlette caches an event bound to the first test's event loop."""
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
        yield

    @pytest.mark.asyncio
    async def test_successful_answer_claims_interaction_and_streams_done(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        interaction = await _open_interaction(db_session, user_id)

        orch = _make_stream_orchestrator(
            events=[("token", {"text": "Listo, aprobado."})],
            result={
                "session_id": str(interaction.session_id), "turn_id": str(uuid.uuid4()),
                "stop_reason": "end_turn", "iterations": 1, "tools_used": [], "awaiting": [],
            },
        )

        with patch("app.api.routers.interactions._get_agent", return_value=orch):
            async with client.stream(
                "POST", f"/interactions/{interaction.id}/answer",
                json={"answer": {"decision": "approve"}},
                headers=headers,
            ) as resp:
                assert resp.status_code == 200
                event_names = [
                    line.split(":", 1)[1].strip()
                    async for line in resp.aiter_lines()
                    if line.startswith("event:")
                ]

        assert event_names == ["token", "done"]

        # The HTTP request claimed and committed via its own session
        # (override_get_db) — db_session's identity map still holds the
        # pre-claim OPEN object from _open_interaction, so query raw SQL
        # rather than through the ORM to see the committed state, same as
        # test_agent_endpoint.py's ConversationTurn persistence checks.
        from sqlalchemy import text
        row = (await db_session.execute(
            text("SELECT status, answer FROM user_interactions WHERE id = :id"),
            {"id": interaction.id.hex},
        )).first()
        assert row is not None
        assert row[0] == "answered"
        assert row[1] == '{"decision": "approve"}'
