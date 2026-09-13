"""Integration tests for the update_commitment action executor — lets the
agent correct a misfiled commitment (wrong owner, resolved, wrong text)
through the propose/approve path, never by writing to the DB directly.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import CommitmentStatus
from app.services.actions.executors.update_commitment import (
    UpdateCommitmentExecutor,
    UpdateCommitmentPayload,
)
from tests.factories import make_commitment, make_user


class TestUpdateCommitmentExecutor:
    @pytest.mark.asyncio
    async def test_reassigns_owner(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id, owner="unknown")
        db_session.add(c)
        await db_session.commit()

        executor = UpdateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, UpdateCommitmentPayload(commitment_id=c.id, owner="Daniel"),
        )

        assert result["owner"] == "Daniel"

    @pytest.mark.asyncio
    async def test_marks_completed(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id)
        db_session.add(c)
        await db_session.commit()

        executor = UpdateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id,
            UpdateCommitmentPayload(commitment_id=c.id, status=CommitmentStatus.COMPLETED),
        )

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_unknown_commitment_returns_error(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        executor = UpdateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, UpdateCommitmentPayload(commitment_id=uuid.uuid4(), owner="Daniel"),
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_cannot_update_another_users_commitment(self, db_session: AsyncSession) -> None:
        owner_user = make_user(email="owner@example.com")
        attacker = make_user(email="attacker@example.com")
        db_session.add_all([owner_user, attacker])
        await db_session.flush()
        c = make_commitment(user_id=owner_user.id, owner="unknown")
        db_session.add(c)
        await db_session.commit()

        executor = UpdateCommitmentExecutor()
        result = await executor.execute(
            db_session, attacker.id, UpdateCommitmentPayload(commitment_id=c.id, owner="Daniel"),
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_status_transition_returns_error(self, db_session: AsyncSession) -> None:
        """The existing pending-only status-transition guard in
        commitment_service.update_commitment still applies here."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        c = make_commitment(user_id=user.id, status=CommitmentStatus.COMPLETED)
        db_session.add(c)
        await db_session.commit()

        executor = UpdateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id,
            UpdateCommitmentPayload(commitment_id=c.id, status=CommitmentStatus.CANCELLED),
        )

        assert "error" in result

    def test_payload_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError):
            UpdateCommitmentPayload(commitment_id=uuid.uuid4(), unexpected="nope")
