"""Integration test for ActionSweeper against a real (test) DB — the unit
tests in tests/unit/test_action_sweeper.py cover the logic with mocked
sessions; this confirms the real SQLAlchemy queries/updates actually work
end-to-end against real ProposedAction/ActionAuditLog rows.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch
import pytest

from app.models.action_audit import ActionAuditLog
from app.models.proposed_action import ActionStatus, ProposedAction
from app.services.actions.sweeper import ActionSweeper, STUCK_EXECUTING_GRACE
from tests.conftest import test_session_factory as _session_factory
from tests.factories import make_user


def _payload_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _create_action(
    db: AsyncSession, user_id: uuid.UUID, *, status: ActionStatus, updated_at_override: datetime,
) -> ProposedAction:
    payload = {"kind": "briefing", "text": "x", "date_str": "2026-09-09"}
    action = ProposedAction(
        user_id=user_id,
        session_id=uuid.uuid4(),
        action_type="notion_publish",
        payload=payload,
        payload_sha256=_payload_hash(payload),
        artifact={"kind": "key_values", "title": "t", "rows": [{"label": "a", "value": "b"}]},
        risk="low",
        status=status,
        idempotency_key=f"sweep:{uuid.uuid4()}",
        executor_version="1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(action)
    await db.commit()
    # updated_at has an onupdate=func.now() default — overwrite it directly
    # via a raw UPDATE so it reflects "stuck since X" rather than "now".
    await db.execute(
        ProposedAction.__table__.update()
        .where(ProposedAction.id == action.id)
        .values(updated_at=updated_at_override)
    )
    await db.commit()
    await db.refresh(action)
    return action


class TestActionSweeperIntegration:
    @pytest.mark.asyncio
    async def test_sweeps_a_genuinely_stuck_action(self, db_session: AsyncSession) -> None:
        user = make_user(email=f"sweep_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.commit()

        stuck_since = datetime.now(timezone.utc) - STUCK_EXECUTING_GRACE - timedelta(minutes=1)
        action = await _create_action(
            db_session, user.id, status=ActionStatus.EXECUTING, updated_at_override=stuck_since,
        )

        sweeper = ActionSweeper()
        with patch("app.services.actions.sweeper.get_session_factory", return_value=_session_factory):
            await sweeper._sweep()

        await db_session.refresh(action)
        assert action.status == ActionStatus.FAILED
        assert action.error is not None and "crashed" in action.error.lower()

        audit_rows = (await db_session.execute(
            select(ActionAuditLog).where(ActionAuditLog.action_id == action.id)
        )).scalars().all()
        assert any(r.event == "failed" and r.actor == "system" for r in audit_rows)

    @pytest.mark.asyncio
    async def test_does_not_sweep_a_recently_executing_action(self, db_session: AsyncSession) -> None:
        user = make_user(email=f"sweep_recent_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.commit()

        recently = datetime.now(timezone.utc) - timedelta(minutes=1)
        action = await _create_action(
            db_session, user.id, status=ActionStatus.EXECUTING, updated_at_override=recently,
        )

        sweeper = ActionSweeper()
        with patch("app.services.actions.sweeper.get_session_factory", return_value=_session_factory):
            await sweeper._sweep()

        await db_session.refresh(action)
        assert action.status == ActionStatus.EXECUTING

    @pytest.mark.asyncio
    async def test_does_not_touch_a_stuck_but_non_executing_action(self, db_session: AsyncSession) -> None:
        """A row that's e.g. long-PROPOSED (never approved) is a different,
        already-handled case (expiry) — the sweeper must only ever touch
        EXECUTING rows."""
        user = make_user(email=f"sweep_proposed_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.commit()

        stuck_since = datetime.now(timezone.utc) - STUCK_EXECUTING_GRACE - timedelta(days=1)
        action = await _create_action(
            db_session, user.id, status=ActionStatus.PROPOSED, updated_at_override=stuck_since,
        )

        sweeper = ActionSweeper()
        with patch("app.services.actions.sweeper.get_session_factory", return_value=_session_factory):
            await sweeper._sweep()

        await db_session.refresh(action)
        assert action.status == ActionStatus.PROPOSED
