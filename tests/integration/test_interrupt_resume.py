"""Integration tests for the request_user_input interrupt/resume mechanism.

This is the highest-risk, newest piece of the generative UI protocol build:
it's the first use in this codebase of Strands' native interrupt/snapshot
API (installed: strands-agents 1.54.0). A fake Agent stands in for the real
one across two calls — the first returns an AgentResult with
stop_reason="interrupt" (mirroring what request_user_input's
tool_context.interrupt() call produces), the second (after load_snapshot +
an interruptResponse prompt) returns a normal completion — so these tests
exercise the orchestrator's own logic (persisting UserInteraction +
AgentSessionState rows, the idempotent claim transition, resuming) against
a real SQLite DB, without ever constructing a real strands.Agent or hitting
an LLM.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strands import Snapshot

from app.models.agent_session_state import AgentSessionState
from app.models.user_interaction import InteractionStatus, UserInteraction
from app.services.agent import interactions_store
from app.services.agent.strands_orchestrator import (
    SnapshotUnavailableError,
    StrandsOrchestrator,
    _installed_strands_version,
    _StreamingCallbackHandler,
)
from tests.factories import make_user


class _FakeAgentResult:
    """Stand-in for strands.agent.agent_result.AgentResult — only the
    fields the orchestrator actually reads."""

    def __init__(self, stop_reason: str, message: Dict[str, Any], interrupts: Optional[List[Any]] = None) -> None:
        self.stop_reason = stop_reason
        self.message = message
        self.interrupts = interrupts


class _FakeInterrupt:
    def __init__(self, id_: str, reason: Dict[str, Any]) -> None:
        self.id = id_
        self.reason = reason


class _FakeAgent:
    """Stand-in for a Strands Agent across one query()/resume() call."""

    def __init__(self, result: _FakeAgentResult) -> None:
        self._result = result
        self.messages: List[Dict[str, Any]] = []
        self.callback_handler = _StreamingCallbackHandler(None)
        self.loaded_snapshot: Optional[Snapshot] = None
        self.take_snapshot_calls = 0

    async def invoke_async(self, prompt: Any) -> _FakeAgentResult:
        return self._result

    async def stream_async(self, prompt: Any):
        yield {"result": self._result}

    def take_snapshot(self, preset: Optional[str] = None) -> Snapshot:
        self.take_snapshot_calls += 1
        return Snapshot(scope="agent", schema_version="1.0", data={"messages": self.messages}, app_data={})

    def load_snapshot(self, snapshot: Snapshot) -> None:
        self.loaded_snapshot = snapshot


def _ui_request_reason(tool_use_id: str = "tu_1") -> Dict[str, Any]:
    return {
        "tool_use_id": tool_use_id,
        "ui_request": {
            "version": "1",
            "request_id": str(uuid.uuid4()),
            "kicker": "needs_datum",
            "prompt": [{"text": "¿Qué decidís?", "emphasis": "none"}],
            "fields": [{
                "key": "decision", "kind": "single_select", "label": "Decisión", "required": True,
                "options": [{"id": "approve", "label": "Aprobar"}, {"id": "reject", "label": "Rechazar"}],
                "default": "approve",
            }],
            "submit_label": "Confirmar",
            "allow_dismiss": True,
        },
    }


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = make_user(email=f"interrupt_{uuid.uuid4().hex[:8]}@test.com")
    db.add(user)
    await db.flush()
    return user.id


class TestQueryPersistsInteractionOnInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_creates_open_interaction_and_snapshot(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        interrupt_id = "v1:tool_call:tu_1:abc"
        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt(interrupt_id, _ui_request_reason())],
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.query(db_session, user_id, "necesito una decisión")
        await db_session.commit()

        assert result["stop_reason"] == "interrupt"
        assert len(result["awaiting"]) == 1
        interaction_id = uuid.UUID(result["awaiting"][0])

        interaction = await db_session.get(UserInteraction, interaction_id)
        assert interaction is not None
        assert interaction.status == InteractionStatus.OPEN
        assert interaction.interrupt_id == interrupt_id
        assert interaction.tool_use_id == "tu_1"
        assert interaction.spec["fields"][0]["key"] == "decision"

        session_id = uuid.UUID(result["session_id"])
        session_state = await interactions_store.get_session_state(db_session, user_id, session_id)
        assert session_state is not None
        assert session_state.awaiting_input is True
        assert fake_agent.take_snapshot_calls == 1

    @pytest.mark.asyncio
    async def test_interrupted_turn_persists_structured_assistant_turn(self, db_session: AsyncSession) -> None:
        """The assistant ConversationTurn's tool_calls must record the
        interaction, not leave it implicit — and content must be the
        rendered question, not an empty extracted-answer string."""
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},  # dangling toolUse — no text
            interrupts=[_FakeInterrupt("v1:tool_call:tu_1:abc", _ui_request_reason())],
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.query(db_session, user_id, "necesito una decisión")
        await db_session.commit()

        from app.models.conversation_turn import ConversationTurn
        rows = (await db_session.execute(
            select(ConversationTurn).where(ConversationTurn.session_id == uuid.UUID(result["session_id"]))
        )).scalars().all()
        assistant_row = next(r for r in rows if r.role == "assistant")
        assert assistant_row.content == "¿Qué decidís?"
        assert assistant_row.tool_calls == [{"type": "ui_request", "interaction_id": result["awaiting"][0]}]

    @pytest.mark.asyncio
    async def test_interrupt_with_no_reason_payload_is_skipped_not_crashed(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt("v1:tool_call:tu_1:abc", reason=None)],  # malformed
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.query(db_session, user_id, "hola")
        assert result["awaiting"] == []


class TestStaleInteractionExpiry:
    """Regression tests for review-round-2 finding #2:
    upsert_session_state keeps only one AgentSessionState row per session,
    so a second interrupt on the same session silently overwrites the
    snapshot an earlier OPEN interaction depends on to resume. Without
    expire_stale_interactions_for_session, answering that earlier
    interaction late would fail deep inside Strands' own
    _InterruptState.resume() with a confusing KeyError instead of a clean,
    immediate 409."""

    @pytest.mark.asyncio
    async def test_second_interrupt_on_same_session_expires_the_earlier_open_interaction(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        first_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt("v1:tool_call:tu_1:abc", _ui_request_reason(tool_use_id="tu_1"))],
        ))
        orch._build_agent = MagicMock(return_value=first_agent)  # type: ignore[method-assign]
        first_result = await orch.query(db_session, user_id, "primera pregunta")
        await db_session.commit()

        session_id = first_result["session_id"]
        first_interaction_id = uuid.UUID(first_result["awaiting"][0])

        second_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt("v1:tool_call:tu_2:def", _ui_request_reason(tool_use_id="tu_2"))],
        ))
        orch._build_agent = MagicMock(return_value=second_agent)  # type: ignore[method-assign]
        second_result = await orch.query(db_session, user_id, "sin contestar, otra cosa", session_id=session_id)
        await db_session.commit()

        second_interaction_id = uuid.UUID(second_result["awaiting"][0])
        assert second_interaction_id != first_interaction_id

        first_interaction = await db_session.get(UserInteraction, first_interaction_id)
        assert first_interaction is not None
        assert first_interaction.status == InteractionStatus.EXPIRED

        second_interaction = await db_session.get(UserInteraction, second_interaction_id)
        assert second_interaction is not None
        assert second_interaction.status == InteractionStatus.OPEN

        # The now-stale interaction must be rejected cleanly (409-shaped
        # None return), not attempted against a snapshot that no longer
        # contains its interrupt_id.
        claimed = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, first_interaction_id, {"decision": "approve"}, "ui",
        )
        assert claimed is None


class TestSameTurnMultipleInterrupts:
    """One LLM turn can request TWO request_user_input calls at once —
    result.interrupts holds both. Strands' interrupt state is a dict
    keyed by interrupt_id (strands/interrupt.py's _InterruptState), so
    answering one sibling via resume() leaves the other's entry
    untouched: it re-raises with the SAME interrupt_id on the next pause.
    Without keep_interrupt_ids/get_or_create_interaction, that sibling's
    still-open row would get swept as abandoned (expire_stale_
    interactions_for_session) right before a blind re-insert would hit
    the (session_id, interrupt_id) unique constraint."""

    @pytest.mark.asyncio
    async def test_both_siblings_persist_open_sharing_one_snapshot(
        self, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[
                _FakeInterrupt("v1:tool_call:tu_1:abc", _ui_request_reason(tool_use_id="tu_1")),
                _FakeInterrupt("v1:tool_call:tu_2:def", _ui_request_reason(tool_use_id="tu_2")),
            ],
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.query(db_session, user_id, "necesito dos decisiones")
        await db_session.commit()

        assert len(result["awaiting"]) == 2
        for interaction_id in result["awaiting"]:
            interaction = await db_session.get(UserInteraction, uuid.UUID(interaction_id))
            assert interaction is not None
            assert interaction.status == InteractionStatus.OPEN

        session_state = await interactions_store.get_session_state(db_session, user_id, uuid.UUID(result["session_id"]))
        assert session_state is not None  # one shared row, by design

    @pytest.mark.asyncio
    async def test_answering_one_sibling_reuses_not_reinserts_the_other_on_repause(
        self, db_session: AsyncSession,
    ) -> None:
        """The core regression: partially resuming (answering A, Strands
        re-pausing on B unchanged) must not crash on a duplicate
        (session_id, interrupt_id), must not expire B as if it were an
        abandoned previous-turn question, and must resolve back to B's
        ORIGINAL UserInteraction row rather than creating a second one."""
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        interrupt_a, interrupt_b = "v1:tool_call:tu_1:abc", "v1:tool_call:tu_2:def"
        first_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[
                _FakeInterrupt(interrupt_a, _ui_request_reason(tool_use_id="tu_1")),
                _FakeInterrupt(interrupt_b, _ui_request_reason(tool_use_id="tu_2")),
            ],
        ))
        orch._build_agent = MagicMock(return_value=first_agent)  # type: ignore[method-assign]
        first_result = await orch.query(db_session, user_id, "necesito dos decisiones")
        await db_session.commit()

        session_id = uuid.UUID(first_result["session_id"])
        awaiting_before = {uuid.UUID(i) for i in first_result["awaiting"]}
        assert len(awaiting_before) == 2

        b_interaction_before = (await db_session.execute(
            select(UserInteraction).where(
                UserInteraction.session_id == session_id, UserInteraction.interrupt_id == interrupt_b,
            )
        )).scalar_one()

        # The router's real flow claims A before ever calling resume() —
        # replicate that here since resume() itself doesn't touch A's row.
        a_interaction = (await db_session.execute(
            select(UserInteraction).where(
                UserInteraction.session_id == session_id, UserInteraction.interrupt_id == interrupt_a,
            )
        )).scalar_one()
        claimed_a = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, a_interaction.id, {"decision": "approve"}, "ui",
        )
        assert claimed_a is not None
        await db_session.commit()

        # Simulate Strands completing A internally and re-pausing on B,
        # UNCHANGED — the exact shape _InterruptState.resume() produces
        # for a still-unanswered sibling.
        second_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt(interrupt_b, _ui_request_reason(tool_use_id="tu_2"))],
        ))
        orch._build_agent = MagicMock(return_value=second_agent)  # type: ignore[method-assign]

        resume_result = await orch.resume(
            db_session, user_id, session_id, interrupt_a, {"decision": "approve"},
        )
        await db_session.commit()  # must not raise IntegrityError on (session_id, interrupt_b)

        assert resume_result["stop_reason"] == "interrupt"
        assert resume_result["awaiting"] == [str(b_interaction_before.id)]

        # No duplicate row for interrupt_b — still exactly one.
        b_rows = (await db_session.execute(
            select(UserInteraction).where(
                UserInteraction.session_id == session_id, UserInteraction.interrupt_id == interrupt_b,
            )
        )).scalars().all()
        assert len(b_rows) == 1
        assert b_rows[0].id == b_interaction_before.id
        assert b_rows[0].status == InteractionStatus.OPEN

        # B must still be answerable — proves it wasn't swept as stale.
        claimed_b = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, b_interaction_before.id, {"decision": "reject"}, "ui",
        )
        assert claimed_b is not None


class TestGetOrCreateInteractionAndKeepInterruptIds:
    """Direct, orchestrator-independent coverage of the two store
    functions TestSameTurnMultipleInterrupts exercises end-to-end."""

    @pytest.mark.asyncio
    async def test_get_or_create_creates_when_absent(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        interaction = await interactions_store.get_or_create_interaction(
            db_session, user_id, session_id, None, "int-new", "tu_1", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()
        assert interaction.status == InteractionStatus.OPEN
        assert interaction.interrupt_id == "int-new"

    @pytest.mark.asyncio
    async def test_get_or_create_reuses_existing_row_untouched(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        original = await interactions_store.create_interaction(
            db_session, user_id, session_id, None, "int-existing", "tu_1", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()

        reused = await interactions_store.get_or_create_interaction(
            db_session, user_id, session_id, None, "int-existing", "tu_1", _ui_request_reason()["ui_request"],
        )
        assert reused.id == original.id
        assert reused.status == InteractionStatus.OPEN

        count = len((await db_session.execute(
            select(UserInteraction).where(UserInteraction.interrupt_id == "int-existing")
        )).scalars().all())
        assert count == 1  # no duplicate inserted

    @pytest.mark.asyncio
    async def test_keep_interrupt_ids_excludes_named_ones_from_expiry(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        keep = await interactions_store.create_interaction(
            db_session, user_id, session_id, None, "int-keep", "tu_1", _ui_request_reason()["ui_request"],
        )
        expire = await interactions_store.create_interaction(
            db_session, user_id, session_id, None, "int-expire", "tu_2", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()

        await interactions_store.expire_stale_interactions_for_session(
            db_session, user_id, session_id, keep_interrupt_ids=["int-keep"],
        )
        await db_session.commit()

        await db_session.refresh(keep)
        await db_session.refresh(expire)
        assert keep.status == InteractionStatus.OPEN
        assert expire.status == InteractionStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_no_keep_interrupt_ids_expires_everything_open(self, db_session: AsyncSession) -> None:
        """Backward-compatible default: omitting keep_interrupt_ids (the
        normal fresh-turn case) still expires every open interaction, same
        as before this parameter existed."""
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        interaction = await interactions_store.create_interaction(
            db_session, user_id, session_id, None, "int-1", "tu_1", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()

        await interactions_store.expire_stale_interactions_for_session(db_session, user_id, session_id)
        await db_session.commit()

        await db_session.refresh(interaction)
        assert interaction.status == InteractionStatus.EXPIRED


class TestClaimInteractionIdempotency:
    @pytest.mark.asyncio
    async def test_second_claim_returns_none(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        interaction = await interactions_store.create_interaction(
            db_session, user_id, session_id, None, "int-1", "tu_1", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()

        first = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, interaction.id, {"decision": "approve"}, "ui",
        )
        await db_session.commit()
        assert first is not None
        assert first.status == InteractionStatus.ANSWERED

        second = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, interaction.id, {"decision": "approve"}, "ui",
        )
        assert second is None

    @pytest.mark.asyncio
    async def test_expired_interaction_cannot_be_claimed(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        interaction = await interactions_store.create_interaction(
            db_session, user_id, uuid.uuid4(), None, "int-2", "tu_2", _ui_request_reason()["ui_request"],
        )
        interaction.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db_session.commit()

        claimed = await interactions_store.claim_interaction_for_answer(
            db_session, user_id, interaction.id, {"decision": "approve"}, "ui",
        )
        assert claimed is None

    @pytest.mark.asyncio
    async def test_wrong_user_cannot_claim(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        other_user_id = await _make_user(db_session)
        interaction = await interactions_store.create_interaction(
            db_session, user_id, uuid.uuid4(), None, "int-3", "tu_3", _ui_request_reason()["ui_request"],
        )
        await db_session.commit()

        claimed = await interactions_store.claim_interaction_for_answer(
            db_session, other_user_id, interaction.id, {"decision": "approve"}, "ui",
        )
        assert claimed is None


class TestResume:
    @pytest.mark.asyncio
    async def test_resume_without_snapshot_raises(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        orch = StrandsOrchestrator()

        with pytest.raises(SnapshotUnavailableError):
            await orch.resume(db_session, user_id, uuid.uuid4(), "int-1", {"decision": "approve"})

    @pytest.mark.asyncio
    async def test_resume_with_mismatched_strands_version_raises(self, db_session: AsyncSession) -> None:
        """A snapshot captured under a different strands-agents version must
        be discarded rather than risk deserializing into a subtly wrong
        shape — Snapshot.validate() only checks Strands' own schema_version
        ("1.0"), which doesn't track the SDK's package version."""
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        orch = StrandsOrchestrator()

        await interactions_store.upsert_session_state(
            db_session, user_id, session_id,
            Snapshot(scope="agent", schema_version="1.0", data={}, app_data={}).to_dict(),
            "0.0.1-not-installed", awaiting_input=True,
        )
        await db_session.commit()

        with pytest.raises(SnapshotUnavailableError):
            await orch.resume(db_session, user_id, session_id, "int-1", {"decision": "approve"})

    @pytest.mark.asyncio
    async def test_resume_loads_snapshot_and_completes(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        orch = StrandsOrchestrator()

        stored_snapshot = Snapshot(
            scope="agent", schema_version="1.0", data={"messages": [{"role": "user", "content": [{"text": "hola"}]}]},
            app_data={},
        )
        await interactions_store.upsert_session_state(
            db_session, user_id, session_id, stored_snapshot.to_dict(), _installed_strands_version(), awaiting_input=True,
        )
        await db_session.commit()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"text": "Listo, aprobado."}]},
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.resume(
            db_session, user_id, session_id, "int-1", {"decision": "approve"},
        )
        await db_session.commit()

        assert result["stop_reason"] == "end_turn"
        assert result["answer"] == "Listo, aprobado."
        assert fake_agent.loaded_snapshot is not None
        assert fake_agent.loaded_snapshot.data == stored_snapshot.data

    @pytest.mark.asyncio
    async def test_resume_persists_readable_user_turn_from_answer_values(self, db_session: AsyncSession) -> None:
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        orch = StrandsOrchestrator()

        await interactions_store.upsert_session_state(
            db_session, user_id, session_id,
            Snapshot(scope="agent", schema_version="1.0", data={}, app_data={}).to_dict(),
            _installed_strands_version(), awaiting_input=True,
        )
        await db_session.commit()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="end_turn", message={"role": "assistant", "content": [{"text": "ok"}]},
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.resume(
            db_session, user_id, session_id, "int-1",
            {"decision": "approve", "comment": "ajustar viajes"},
        )
        await db_session.commit()

        from app.models.conversation_turn import ConversationTurn
        rows = (await db_session.execute(
            select(ConversationTurn).where(ConversationTurn.session_id == uuid.UUID(result["session_id"]))
        )).scalars().all()
        user_row = next(r for r in rows if r.role == "user")
        assert "decision: approve" in user_row.content
        assert "comment: ajustar viajes" in user_row.content

    @pytest.mark.asyncio
    async def test_resume_can_pause_again_on_a_chained_interrupt(self, db_session: AsyncSession) -> None:
        """A resumed turn that immediately needs a second clarification
        must persist a new UserInteraction, not silently drop it."""
        user_id = await _make_user(db_session)
        session_id = uuid.uuid4()
        orch = StrandsOrchestrator()

        await interactions_store.upsert_session_state(
            db_session, user_id, session_id,
            Snapshot(scope="agent", schema_version="1.0", data={}, app_data={}).to_dict(),
            _installed_strands_version(), awaiting_input=True,
        )
        await db_session.commit()

        fake_agent = _FakeAgent(_FakeAgentResult(
            stop_reason="interrupt",
            message={"role": "assistant", "content": []},
            interrupts=[_FakeInterrupt("v1:tool_call:tu_2:def", _ui_request_reason(tool_use_id="tu_2"))],
        ))
        orch._build_agent = MagicMock(return_value=fake_agent)  # type: ignore[method-assign]

        result = await orch.resume(db_session, user_id, session_id, "int-1", {"decision": "changes"})
        await db_session.commit()

        assert result["stop_reason"] == "interrupt"
        assert len(result["awaiting"]) == 1
        new_interaction = await db_session.get(UserInteraction, uuid.UUID(result["awaiting"][0]))
        assert new_interaction is not None
        assert new_interaction.tool_use_id == "tu_2"
