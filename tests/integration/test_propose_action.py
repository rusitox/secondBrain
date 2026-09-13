"""Integration tests for the propose_action tool (strands_tools.py) — the
model-facing half of the action gate. Execution
(POST /interactions/actions/{id}/approve, tests/integration/
test_approve_action.py) is a separate, non-LLM code path; these tests
cover what propose_action itself can and cannot do: it can create a
ProposedAction row and an audit entry, but nothing here — or anywhere
reachable from strands_tools.py — can transition that row past "proposed".
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_audit import ActionAuditLog
from app.models.proposed_action import ActionStatus, ProposedAction
from app.services.actions.registry import _REGISTRY
from app.services.agent.strands_tools import make_agent_tools
from tests.conftest import test_session_factory as _session_factory
from tests.factories import make_user


def _make_settings(enable_generative_ui: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.brave_search_api_key = ""
    settings.http_request_allowed_domains = ""
    settings.enable_generative_ui = enable_generative_ui
    return settings


def _tool(tools: Any, name: str):
    return next(t for t in tools if t.tool_name == name).__wrapped__


async def _make_persisted_user(db: AsyncSession) -> uuid.UUID:
    user = make_user(email=f"propose_{uuid.uuid4().hex[:8]}@test.com")
    db.add(user)
    await db.commit()
    return user.id


_ARTIFACT = {
    "kind": "key_values",
    "title": "Publicar en Notion",
    "rows": [{"label": "Fecha", "value": "2026-09-09"}],
}


class TestDescribeActionTypes:
    """describe_action_types — lets the model discover the exact payload
    shape for a registered action_type instead of guessing it, which was
    the single most common way propose_action failed in practice (see
    project memory: forcing propose_action via natural-language prompts
    without this tool took 3 attempts to get a valid payload)."""

    @pytest.mark.asyncio
    async def test_lists_registered_notion_publish_with_its_real_schema(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "describe_action_types")()

        notion = next(d for d in result if d["action_type"] == "notion_publish")
        assert notion["risk"] == "low"
        assert set(notion["required_fields"]) == {"kind", "text", "date_str"}
        assert "kind" in notion["payload_fields"]

    @pytest.mark.asyncio
    async def test_disabled_when_generative_ui_flag_is_off(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings(enable_generative_ui=False)):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        assert not any(t.tool_name == "describe_action_types" for t in tools)


class TestProposeActionValidation:
    @pytest.mark.asyncio
    async def test_unregistered_action_type_returns_error_without_writing_a_row(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "propose_action")(
            action_type="send_email", payload={}, artifact=_ARTIFACT,
        )
        assert "error" in result

        count = len((await db_session.execute(select(ProposedAction))).scalars().all())
        assert count == 0

    @pytest.mark.asyncio
    async def test_invalid_payload_for_registered_type_returns_error(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "propose_action")(
            action_type="notion_publish",
            payload={"kind": "briefing"},  # missing required "text"/"date_str"
            artifact=_ARTIFACT,
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_risk_value_returns_error(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "propose_action")(
            action_type="notion_publish",
            payload={"kind": "briefing", "text": "hola", "date_str": "2026-09-09"},
            artifact=_ARTIFACT,
            risk="extreme",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_artifact_kind_returns_error(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "propose_action")(
            action_type="notion_publish",
            payload={"kind": "briefing", "text": "hola", "date_str": "2026-09-09"},
            artifact={"kind": "not_a_real_kind"},
        )
        assert "error" in result


class TestProposeActionSuccess:
    @pytest.mark.asyncio
    async def test_valid_proposal_creates_row_and_audit_entry(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session)
        session_id = uuid.uuid4()
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=session_id)

        result = await _tool(tools, "propose_action")(
            action_type="notion_publish",
            payload={"kind": "briefing", "text": "Resumen del día", "date_str": "2026-09-09"},
            artifact=_ARTIFACT,
            risk="low",
        )
        await db_session.commit()

        assert result["status"] == "proposed"
        action_id = uuid.UUID(result["action_id"])

        action = await db_session.get(ProposedAction, action_id)
        assert action is not None
        assert action.status == ActionStatus.PROPOSED
        assert action.action_type == "notion_publish"
        assert action.session_id == session_id
        assert action.user_id == user_id
        assert action.artifact["kind"] == "key_values"
        assert len(action.payload_sha256) == 64  # sha256 hex digest

        audit_rows = (await db_session.execute(
            select(ActionAuditLog).where(ActionAuditLog.action_id == action_id)
        )).scalars().all()
        assert len(audit_rows) == 1
        assert audit_rows[0].event == "proposed"
        assert audit_rows[0].actor == "agent"

    @pytest.mark.asyncio
    async def test_identical_proposal_is_idempotent(self, db_session: AsyncSession) -> None:
        """The exact same action_type+payload proposed twice must not
        create a second row — propose_action returns the existing one."""
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        payload = {"kind": "briefing", "text": "Mismo texto", "date_str": "2026-09-09"}
        first = await _tool(tools, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )
        await db_session.commit()
        second = await _tool(tools, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )

        assert first["action_id"] == second["action_id"]
        assert "note" in second

        count = len((await db_session.execute(select(ProposedAction))).scalars().all())
        assert count == 1

    @pytest.mark.asyncio
    async def test_no_tool_can_transition_a_proposed_action_past_proposed(
        self, db_session: AsyncSession,
    ) -> None:
        """The whole point of the gate: nothing in the tool surface can
        move a row to approved/executed. Confirmed structurally — no tool
        named anything execute/approve-shaped exists."""
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        tool_names = {t.tool_name for t in tools}
        assert not any(
            keyword in name for name in tool_names for keyword in ("approve", "execute_action")
        )

    @pytest.mark.asyncio
    async def test_two_users_proposing_identical_payloads_get_separate_rows(
        self, db_session: AsyncSession,
    ) -> None:
        """The idempotency key must be scoped per-user — otherwise the
        second user's identical proposal would silently return the first
        user's action_id instead of creating their own, and later fail
        approve_action's ownership check with a confusing 404."""
        user_a = await _make_persisted_user(db_session)
        user_b = await _make_persisted_user(db_session)
        payload = {"kind": "briefing", "text": "Mismo texto para dos usuarios", "date_str": "2026-09-09"}

        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools_a = make_agent_tools(db=db_session, user_id=user_a, session_id=uuid.uuid4())
            tools_b = make_agent_tools(db=db_session, user_id=user_b, session_id=uuid.uuid4())

        result_a = await _tool(tools_a, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )
        await db_session.commit()
        result_b = await _tool(tools_b, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )
        await db_session.commit()

        assert result_a["action_id"] != result_b["action_id"]
        assert "note" not in result_b  # a genuinely new row, not a dedup hit

        action_a = await db_session.get(ProposedAction, uuid.UUID(result_a["action_id"]))
        action_b = await db_session.get(ProposedAction, uuid.UUID(result_b["action_id"]))
        assert action_a is not None and action_a.user_id == user_a
        assert action_b is not None and action_b.user_id == user_b


class TestProposeActionIdempotencyRevivalAndRace:
    """Regression tests for review-round-2 finding #1: propose_action's
    idempotency_key has a DB-level UNIQUE constraint, so a naive
    check-then-insert either dead-ends forever on a terminal-state row
    (EXPIRED/FAILED/REJECTED) or crashes on a genuine insert race between
    two identical proposals."""

    @pytest.mark.asyncio
    async def test_expired_action_is_revived_to_proposed_not_dead_ended(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        payload = {"kind": "briefing", "text": "Texto original", "date_str": "2026-09-09"}
        first = await _tool(tools, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )
        await db_session.commit()
        action_id = uuid.UUID(first["action_id"])

        action = await db_session.get(ProposedAction, action_id)
        assert action is not None
        action.status = ActionStatus.EXPIRED
        action.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.commit()

        revived = await _tool(tools, "propose_action")(
            action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
        )
        await db_session.commit()

        # Same row is reused (the UNIQUE constraint on idempotency_key makes
        # a second row impossible), not a dead end the caller can never
        # act on again.
        assert revived["action_id"] == first["action_id"]
        assert revived["status"] == "proposed"
        assert "note" not in revived  # distinguishes revival from a plain dedup hit

        count = len((await db_session.execute(select(ProposedAction))).scalars().all())
        assert count == 1

        await db_session.refresh(action)
        assert action.status == ActionStatus.PROPOSED
        # SQLite round-trips this as a naive datetime regardless of what was
        # stored — compare naive-to-naive rather than assume tz-awareness.
        assert action.expires_at.replace(tzinfo=None) > datetime.now(timezone.utc).replace(tzinfo=None)

        audit_rows = (await db_session.execute(
            select(ActionAuditLog).where(ActionAuditLog.action_id == action_id)
        )).scalars().all()
        assert [r.event for r in audit_rows] == ["proposed", "proposed"]
        assert any(
            r.detail is not None and r.detail.get("revived_from") == "expired/failed/rejected"
            for r in audit_rows
        )

    @pytest.mark.asyncio
    async def test_concurrent_identical_proposal_falls_back_to_the_winning_row(
        self, db_session: AsyncSession,
    ) -> None:
        """Simulates a second request winning the INSERT race between this
        call's own idempotency SELECT (finds nothing) and its INSERT: a
        competing row with the same idempotency_key is committed by another
        session in between, via those two points via a monkeypatched
        db.execute. propose_action's IntegrityError catch must fall back to
        that winning row instead of crashing the whole turn."""
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        payload = {"kind": "briefing", "text": "Carrera de propuestas", "date_str": "2026-09-09"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
        idempotency_key = f"{user_id}:notion_publish:{payload_sha256}"

        winner_id = uuid.uuid4()
        original_execute = db_session.execute
        state = {"calls": 0}

        async def racing_execute(*args: Any, **kwargs: Any) -> Any:
            result = await original_execute(*args, **kwargs)
            state["calls"] += 1
            if state["calls"] == 1:
                # This is propose_action's own idempotency SELECT, which
                # just found nothing — a concurrent request now wins the
                # race by committing first, from a genuinely separate
                # session/connection.
                async with _session_factory() as other:
                    other.add(ProposedAction(
                        id=winner_id,
                        user_id=user_id,
                        session_id=uuid.uuid4(),
                        action_type="notion_publish",
                        payload=payload,
                        payload_sha256=payload_sha256,
                        artifact=_ARTIFACT,
                        risk="low",
                        status=ActionStatus.PROPOSED,
                        idempotency_key=idempotency_key,
                        executor_version="1",
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                    ))
                    await other.commit()
            return result

        db_session.execute = racing_execute  # type: ignore[method-assign]
        try:
            result = await _tool(tools, "propose_action")(
                action_type="notion_publish", payload=payload, artifact=_ARTIFACT,
            )
        finally:
            db_session.execute = original_execute  # type: ignore[method-assign]
        await db_session.commit()

        assert result["action_id"] == str(winner_id)
        assert "note" in result  # fell back to the row that won the race

        rows = (await db_session.execute(
            select(ProposedAction).where(ProposedAction.idempotency_key == idempotency_key)
        )).scalars().all()
        assert len(rows) == 1  # our own insert attempt was rolled back, not left as a duplicate
        assert rows[0].id == winner_id


class _HighRiskPayload:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def model_dump(self) -> dict:
        return {}


class _HighRiskExecutor:
    action_type = "test_high_risk_action"
    version = "1"
    risk = "high"

    payload_model = _HighRiskPayload

    async def execute(self, db: Any, user_id: Any, payload: Any) -> dict:
        return {"ok": True}


class TestProposeActionRiskFloor:
    def setup_method(self) -> None:
        self._saved = dict(_REGISTRY)
        _REGISTRY[_HighRiskExecutor.action_type] = _HighRiskExecutor()

    def teardown_method(self) -> None:
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    @pytest.mark.asyncio
    async def test_self_reported_low_risk_is_escalated_to_executors_floor(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session)
        with patch("app.core.config.get_settings", return_value=_make_settings()):
            tools = make_agent_tools(db=db_session, user_id=user_id, session_id=uuid.uuid4())

        result = await _tool(tools, "propose_action")(
            action_type="test_high_risk_action", payload={}, artifact=_ARTIFACT, risk="low",
        )

        assert result["risk"] == "high"
        action = await db_session.get(ProposedAction, uuid.UUID(result["action_id"]))
        assert action is not None
        assert action.risk == "high"
