"""Unit tests for app/services/agent/interactions_store.py constants.

Regression test for review-round-2 finding #8: UserInteraction.expires_at
used to be a 7-day window while AgentSessionState.expires_at (the
resumability snapshot it depends on) was only 24 hours. An interaction
could look answerable for days after its own snapshot was already gone,
permanently burning it (claim_interaction_for_answer marks it ANSWERED)
on a resume attempt doomed to raise SnapshotUnavailableError. Both are
created in the same _finalize_turn transaction, so keeping the two
durations equal closes that gap to effectively zero instead of days.
"""
from datetime import timedelta

from app.services.agent import interactions_store


def test_interaction_expiry_matches_session_state_expiry() -> None:
    assert interactions_store.INTERACTION_EXPIRY == timedelta(
        hours=interactions_store.SESSION_STATE_EXPIRY_HOURS
    )
