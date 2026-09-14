"""Integration tests for the create_commitment action executor — lets the
agent add a task to the backlog (description, optional due date, optional
recipient) through the propose/approve path, never by writing to the DB
directly from a tool.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment
from app.services.actions.executors.create_commitment import (
    CreateCommitmentExecutor,
    CreateCommitmentPayload,
)
from tests.factories import make_user


class TestCreateCommitmentExecutor:
    @pytest.mark.asyncio
    async def test_creates_with_only_description(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        executor = CreateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, CreateCommitmentPayload(commitment_text="Mandar el reporte"),
        )

        assert result["commitment_text"] == "Mandar el reporte"
        assert result["owner"] == "assistant"
        assert result["due_date"] is None
        assert result["delivered_to"] is None
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_creates_with_due_date_and_recipient(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        due = datetime(2026, 9, 19, tzinfo=timezone.utc)
        executor = CreateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, CreateCommitmentPayload(
                commitment_text="Mandar el reporte a Marilyn",
                due_date=due,
                delivered_to="Marilyn",
            ),
        )

        assert result["due_date"].startswith("2026-09-19")
        assert result["delivered_to"] == "Marilyn"

    @pytest.mark.asyncio
    async def test_persists_to_the_database(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        executor = CreateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, CreateCommitmentPayload(commitment_text="Persisted task"),
        )

        row = (await db_session.execute(
            select(Commitment).where(Commitment.id == uuid.UUID(result["commitment_id"]))
        )).scalar_one()
        assert row.commitment_text == "Persisted task"
        assert row.owner == "assistant"

    def test_payload_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError):
            CreateCommitmentPayload(commitment_text="x", unexpected="nope")

    def test_payload_rejects_commitment_text_over_max_length(self) -> None:
        with pytest.raises(ValueError):
            CreateCommitmentPayload(commitment_text="x" * 2001)

    def test_payload_rejects_delivered_to_over_max_length(self) -> None:
        with pytest.raises(ValueError):
            CreateCommitmentPayload(commitment_text="x", delivered_to="y" * 201)

    @pytest.mark.asyncio
    async def test_created_task_is_visible_as_the_users_own(self, db_session: AsyncSession) -> None:
        """owner="assistant" must pass commitment_service.is_owned_by_user —
        otherwise the task the agent just created is invisible to list_tasks
        and the daily briefing's "your commitments" filtering."""
        from app.services.commitment_service import is_owned_by_user

        user = make_user()
        db_session.add(user)
        await db_session.commit()

        executor = CreateCommitmentExecutor()
        result = await executor.execute(
            db_session, user.id, CreateCommitmentPayload(commitment_text="Visible task"),
        )

        assert is_owned_by_user(result["owner"], user) is True
