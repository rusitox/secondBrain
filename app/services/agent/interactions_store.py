"""Persistence for the generative UI protocol's runtime state: open
UserInteraction rows (structured questions raised via the request_user_input
tool through Strands' native interrupt mechanism) and the AgentSessionState
snapshot they resume from. See app/models/user_interaction.py for why these
are separate tables from PendingQuestion, and
app/services/agent/strands_orchestrator.py for how they're used.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_session_state import AgentSessionState
from app.models.user_interaction import InteractionStatus, UserInteraction

# Mirrors StrandsOrchestrator.SESSION_EXPIRY_HOURS — a paused snapshot is
# only useful as long as the conversation session itself would still be
# considered live.
SESSION_STATE_EXPIRY_HOURS = 24
# Deliberately equal to SESSION_STATE_EXPIRY_HOURS, not a longer window
# (this used to be 7 days): an interaction that's still "open" past its
# snapshot's own expiry looks answerable but can never actually resume —
# claim_interaction_for_answer would mark it ANSWERED, resume() would then
# fail with SnapshotUnavailableError, and the interaction could never be
# retried (already consumed). Both are created in the same transaction
# (_finalize_turn), so equal durations close that gap to milliseconds
# instead of days. A sweep to explicitly mark stragglers EXPIRED is still
# Fase 5 hardening; today an expired-but-unswept row is rejected by
# claim_interaction_for_answer's expiry check regardless.
INTERACTION_EXPIRY = timedelta(hours=SESSION_STATE_EXPIRY_HOURS)


async def create_interaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: Optional[uuid.UUID],
    interrupt_id: str,
    tool_use_id: str,
    spec: Dict[str, Any],
) -> UserInteraction:
    """Record a newly-raised request_user_input interrupt as an open interaction."""
    interaction = UserInteraction(
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        interrupt_id=interrupt_id,
        tool_use_id=tool_use_id,
        spec=spec,
        status=InteractionStatus.OPEN,
        expires_at=datetime.now(timezone.utc) + INTERACTION_EXPIRY,
    )
    db.add(interaction)
    await db.flush()
    return interaction


async def expire_stale_interactions_for_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID,
    keep_interrupt_ids: Optional[Iterable[str]] = None,
) -> None:
    """Mark any still-OPEN interactions for this session as EXPIRED.

    Call this right before a new interrupt overwrites the session's one
    AgentSessionState row (upsert_session_state keeps only one snapshot per
    session_id). Without it, an older open interaction from a previous
    turn looks answerable indefinitely, but resume() would load the NEW
    snapshot and fail to find the OLD interrupt_id in it — a confusing
    mid-resume KeyError from Strands' own _InterruptState.resume() instead
    of a clean, immediate rejection when the human tries to answer it late.

    ``keep_interrupt_ids``: interrupt ids to exclude from expiry — pass the
    interrupt ids Strands just re-raised on THIS finalize call. A single
    turn that pauses on multiple simultaneous interrupts (e.g. two
    request_user_input calls in one model response) can legitimately
    re-raise the SAME interrupt_id again after a partial resume answers
    only one of the siblings (Strands' interrupt state is a dict keyed by
    interrupt_id — answering one doesn't touch the others, so they
    re-raise unchanged; see strands/interrupt.py's _InterruptState.resume).
    Without this exclusion, that sibling's still-legitimately-open row
    would get swept as if it were an abandoned PREVIOUS turn's question,
    right before get_or_create_interaction below would otherwise have
    reused it.
    """
    stmt = update(UserInteraction).where(
        UserInteraction.user_id == user_id,
        UserInteraction.session_id == session_id,
        UserInteraction.status == InteractionStatus.OPEN,
    )
    if keep_interrupt_ids:
        stmt = stmt.where(UserInteraction.interrupt_id.notin_(list(keep_interrupt_ids)))
    await db.execute(
        stmt.values(status=InteractionStatus.EXPIRED),
        execution_options={"synchronize_session": "fetch"},
    )


async def get_or_create_interaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: Optional[uuid.UUID],
    interrupt_id: str,
    tool_use_id: str,
    spec: Dict[str, Any],
) -> UserInteraction:
    """Like create_interaction, but idempotent on (session_id,
    interrupt_id) — needed for the same-turn multi-interrupt case
    expire_stale_interactions_for_session's ``keep_interrupt_ids`` docs:
    when Strands re-raises a sibling interrupt unchanged after a partial
    resume, this reuses its existing OPEN row (untouched — status,
    answer, and original turn_id all stay as they were) instead of a
    blind INSERT, which would violate the (session_id, interrupt_id)
    unique constraint since that row is still there.
    """
    existing = (await db.execute(
        select(UserInteraction).where(
            UserInteraction.session_id == session_id,
            UserInteraction.interrupt_id == interrupt_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    return await create_interaction(db, user_id, session_id, turn_id, interrupt_id, tool_use_id, spec)


async def get_interaction(
    db: AsyncSession, user_id: uuid.UUID, interaction_id: uuid.UUID,
) -> Optional[UserInteraction]:
    result = await db.execute(
        select(UserInteraction).where(
            UserInteraction.id == interaction_id, UserInteraction.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def claim_interaction_for_answer(
    db: AsyncSession,
    user_id: uuid.UUID,
    interaction_id: uuid.UUID,
    answer: Dict[str, Any],
    answered_via: str,
) -> Optional[UserInteraction]:
    """Atomically transition an OPEN interaction to ANSWERED.

    Returns None if the row wasn't open (already answered/cancelled/expired,
    or doesn't belong to this user) — the caller must treat that as a 409,
    never retry the transition. This is the interaction-table analogue of
    confirm_pending_answer's status guard (strands_tools.py), and exists for
    the same reason: a retried request or a double-submit must be a no-op,
    not a second resume of an already-consumed interrupt.

    ``synchronize_session="fetch"``: the default "evaluate" strategy
    additionally re-checks the WHERE clause in Python against any matching
    object already in this session's identity map (e.g. one a prior
    ``get_interaction`` call loaded), and SQLite/asyncpg can both return a
    naive ``expires_at`` there, which blows up comparing it against an
    aware ``now``. "fetch" resolves matching rows with a real SQL SELECT
    instead of a Python-side evaluator, and correctly refreshes any
    already-identity-mapped object's attributes from the update — unlike
    ``synchronize_session=False``, which leaves such an object's attributes
    stale (still reading the pre-update status) even though the UPDATE
    itself succeeded.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(UserInteraction)
        .where(
            UserInteraction.id == interaction_id,
            UserInteraction.user_id == user_id,
            UserInteraction.status == InteractionStatus.OPEN,
            UserInteraction.expires_at > now,
        )
        .values(
            status=InteractionStatus.ANSWERED, answer=answer, answered_at=now, answered_via=answered_via,
        )
        .returning(UserInteraction),
        execution_options={"synchronize_session": "fetch"},
    )
    return result.scalar_one_or_none()


async def upsert_session_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    snapshot: Dict[str, Any],
    strands_version: str,
    awaiting_input: bool,
) -> None:
    """Save (or replace) the paused Agent snapshot for a session.

    One row per session — a fresh interrupt on the same session overwrites
    the prior snapshot rather than accumulating history, since Strands'
    "session" preset snapshot already contains the full message history.
    """
    existing = await get_session_state(db, user_id, session_id)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_STATE_EXPIRY_HOURS)
    if existing is not None:
        existing.snapshot = snapshot
        existing.strands_version = strands_version
        existing.awaiting_input = awaiting_input
        existing.expires_at = expires_at
        await db.flush()
        return

    # Nothing loaded for this session_id — but it carries a
    # UniqueConstraint, and a concurrent request (two tabs both racing the
    # session's first-ever interrupt) can INSERT between our SELECT above
    # and this INSERT. Wrapped in a savepoint so a collision only rolls
    # back this insert attempt, not the caller's whole transaction, and is
    # retried as an update against whichever row won the race.
    try:
        async with db.begin_nested():
            db.add(AgentSessionState(
                user_id=user_id,
                session_id=session_id,
                snapshot=snapshot,
                strands_version=strands_version,
                awaiting_input=awaiting_input,
                expires_at=expires_at,
            ))
            await db.flush()
    except IntegrityError:
        winner = await get_session_state(db, user_id, session_id)
        if winner is None:
            raise
        winner.snapshot = snapshot
        winner.strands_version = strands_version
        winner.awaiting_input = awaiting_input
        winner.expires_at = expires_at
        await db.flush()


async def get_session_state(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID,
) -> Optional[AgentSessionState]:
    result = await db.execute(
        select(AgentSessionState).where(
            AgentSessionState.user_id == user_id, AgentSessionState.session_id == session_id,
        )
    )
    return result.scalar_one_or_none()
