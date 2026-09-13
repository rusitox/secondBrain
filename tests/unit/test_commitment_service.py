"""Unit tests for commitment_service, focused on is_owned_by_user."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.commitment import CommitmentUpdate
from app.models.commitment import CommitmentStatus
from app.models.user import User
from app.services.commitment_service import is_owned_by_user, update_commitment
from tests.factories import make_commitment, make_user as make_persisted_user


def make_user(full_name: str = "Mariano Ortega", email: str = "mariano.ortega@gmail.com") -> User:
    return User(full_name=full_name, email=email)


class TestIsOwnedByUser:
    def test_matches_full_name_case_insensitive(self) -> None:
        assert is_owned_by_user("MARIANO ORTEGA", make_user()) is True

    def test_matches_first_name(self) -> None:
        assert is_owned_by_user("Mariano", make_user()) is True

    def test_matches_email(self) -> None:
        assert is_owned_by_user("mariano.ortega@gmail.com", make_user()) is True

    def test_matches_email_local_part(self) -> None:
        assert is_owned_by_user("mariano.ortega", make_user()) is True

    def test_rejects_third_party_name(self) -> None:
        assert is_owned_by_user("Daniel", make_user()) is False

    def test_rejects_third_party_email(self) -> None:
        assert is_owned_by_user("daniel@company.com", make_user()) is False

    def test_rejects_unknown(self) -> None:
        assert is_owned_by_user("unknown", make_user()) is False

    def test_rejects_speaker(self) -> None:
        assert is_owned_by_user("Speaker", make_user()) is False

    def test_rejects_empty_owner(self) -> None:
        assert is_owned_by_user("", make_user()) is False

    def test_rejects_none_owner(self) -> None:
        assert is_owned_by_user(None, make_user()) is False

    def test_rejects_when_user_is_none(self) -> None:
        assert is_owned_by_user("Mariano Ortega", None) is False

    def test_does_not_substring_match_similar_names(self) -> None:
        """"Daniela" must not match a "Daniel" owner via loose substring checks."""
        user = make_user(full_name="Daniela Perez", email="daniela.perez@company.com")
        assert is_owned_by_user("Daniel", user) is False


class TestUpdateCommitmentOwnerAndText:
    """CommitmentUpdate.owner/commitment_text — added so the agent can
    correct a misfiled commitment (see the update_commitment action
    executor), not just change status/due_date/priority."""

    @pytest.mark.asyncio
    async def test_reassigns_owner(self, db_session: AsyncSession) -> None:
        user = make_persisted_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id, owner="unknown")
        db_session.add(c)
        await db_session.commit()

        updated = await update_commitment(db_session, c, CommitmentUpdate(owner="Daniel"))

        assert updated.owner == "Daniel"

    @pytest.mark.asyncio
    async def test_corrects_commitment_text(self, db_session: AsyncSession) -> None:
        user = make_persisted_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id, commitment_text="Send the report")
        db_session.add(c)
        await db_session.commit()

        updated = await update_commitment(
            db_session, c, CommitmentUpdate(commitment_text="Send the quarterly report"),
        )

        assert updated.commitment_text == "Send the quarterly report"

    @pytest.mark.asyncio
    async def test_owner_reassignment_does_not_require_pending_status(
        self, db_session: AsyncSession,
    ) -> None:
        """Correcting attribution on an already-completed commitment must
        not be blocked by the pending-only status-transition guard, since
        no status change is being requested here."""
        user = make_persisted_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id, owner="unknown", status=CommitmentStatus.COMPLETED)
        db_session.add(c)
        await db_session.commit()

        updated = await update_commitment(db_session, c, CommitmentUpdate(owner="Daniel"))

        assert updated.owner == "Daniel"
        assert updated.status == CommitmentStatus.COMPLETED
