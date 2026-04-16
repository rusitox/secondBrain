"""Integration tests for database CRUD operations.

These tests use SQLite in-memory via the test fixtures.
For full pgvector testing, use testcontainers with PostgreSQL.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.models.document import Document
from app.models.identity import Identity
from app.models.integration import Integration, Platform
from app.models.user import User
from tests.factories import (
    make_commitment,
    make_document,
    make_identity,
    make_integration,
    make_user,
)


class TestUserCRUD:
    async def test_create_user(self, db_session: AsyncSession) -> None:
        user = make_user(email="alice@example.com", full_name="Alice")
        db_session.add(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.email == "alice@example.com"))
        fetched = result.scalar_one()
        assert fetched.full_name == "Alice"
        assert fetched.timezone == "UTC"

    async def test_create_user_duplicate_email(self, db_session: AsyncSession) -> None:
        user1 = make_user(email="dup@example.com")
        user2 = make_user(email="dup@example.com", full_name="Another")
        db_session.add(user1)
        await db_session.commit()

        db_session.add(user2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_update_user(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        user.full_name = "Updated Name"
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched = result.scalar_one()
        assert fetched.full_name == "Updated Name"

    async def test_delete_user(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        assert result.scalar_one_or_none() is None


class TestCascadeDeletes:
    async def test_delete_user_cascades_documents(self, db_session: AsyncSession) -> None:
        user = make_user(email="cascade@example.com")
        db_session.add(user)
        await db_session.commit()

        doc = make_document(user_id=user.id)
        db_session.add(doc)
        await db_session.commit()

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(Document))
        assert result.scalar_one_or_none() is None

    async def test_delete_user_cascades_commitments(self, db_session: AsyncSession) -> None:
        user = make_user(email="cascade2@example.com")
        db_session.add(user)
        await db_session.commit()

        commitment = make_commitment(user_id=user.id)
        db_session.add(commitment)
        await db_session.commit()

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(Commitment))
        assert result.scalar_one_or_none() is None

    async def test_delete_user_cascades_identities(self, db_session: AsyncSession) -> None:
        user = make_user(email="cascade3@example.com")
        db_session.add(user)
        await db_session.commit()

        identity = make_identity(user_id=user.id)
        db_session.add(identity)
        await db_session.commit()

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(Identity))
        assert result.scalar_one_or_none() is None

    async def test_delete_user_cascades_integrations(self, db_session: AsyncSession) -> None:
        user = make_user(email="cascade4@example.com")
        db_session.add(user)
        await db_session.commit()

        integration = make_integration(user_id=user.id)
        db_session.add(integration)
        await db_session.commit()

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(Integration))
        assert result.scalar_one_or_none() is None


class TestIdentityCRUD:
    async def test_create_identity(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        identity = make_identity(user_id=user.id)
        db_session.add(identity)
        await db_session.commit()

        result = await db_session.execute(
            select(Identity).where(Identity.user_id == user.id)
        )
        fetched = result.scalar_one()
        assert fetched.persona_description == "A professional assistant"

    async def test_identity_heuristics_jsonb(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        identity = make_identity(
            user_id=user.id,
            heuristics={"priority_rule": "Always prioritize client requests"},
        )
        db_session.add(identity)
        await db_session.commit()

        result = await db_session.execute(
            select(Identity).where(Identity.id == identity.id)
        )
        fetched = result.scalar_one()
        assert fetched.heuristics["priority_rule"] == "Always prioritize client requests"


class TestIntegrationCRUD:
    async def test_create_integration(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        integration = make_integration(user_id=user.id, platform=Platform.OUTLOOK)
        db_session.add(integration)
        await db_session.commit()

        result = await db_session.execute(
            select(Integration).where(Integration.user_id == user.id)
        )
        fetched = result.scalar_one()
        assert fetched.platform == Platform.OUTLOOK
        assert fetched.is_active is True

    async def test_toggle_integration(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        integration = make_integration(user_id=user.id)
        db_session.add(integration)
        await db_session.commit()

        integration.is_active = False
        await db_session.commit()

        result = await db_session.execute(
            select(Integration).where(Integration.id == integration.id)
        )
        fetched = result.scalar_one()
        assert fetched.is_active is False


class TestDocumentCRUD:
    async def test_create_document(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        doc = make_document(user_id=user.id, content="Meeting notes from standup")
        db_session.add(doc)
        await db_session.commit()

        result = await db_session.execute(
            select(Document).where(Document.user_id == user.id)
        )
        fetched = result.scalar_one()
        assert fetched.content == "Meeting notes from standup"
        assert fetched.source == "slack"

    async def test_document_metadata(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        doc = make_document(
            user_id=user.id,
            metadata_={"author": "John", "thread_id": "t-123"},
        )
        db_session.add(doc)
        await db_session.commit()

        result = await db_session.execute(
            select(Document).where(Document.id == doc.id)
        )
        fetched = result.scalar_one()
        assert fetched.metadata_["author"] == "John"


class TestCommitmentCRUD:
    async def test_create_commitment(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        commitment = make_commitment(user_id=user.id)
        db_session.add(commitment)
        await db_session.commit()

        result = await db_session.execute(
            select(Commitment).where(Commitment.user_id == user.id)
        )
        fetched = result.scalar_one()
        assert fetched.commitment_text == "Send the report by Friday"
        assert fetched.status == CommitmentStatus.PENDING

    async def test_update_commitment_status(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        commitment = make_commitment(user_id=user.id)
        db_session.add(commitment)
        await db_session.commit()

        commitment.status = CommitmentStatus.COMPLETED
        await db_session.commit()

        result = await db_session.execute(
            select(Commitment).where(Commitment.id == commitment.id)
        )
        fetched = result.scalar_one()
        assert fetched.status == CommitmentStatus.COMPLETED

    async def test_commitment_linked_to_document(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        doc = make_document(user_id=user.id)
        db_session.add(doc)
        await db_session.commit()

        commitment = make_commitment(user_id=user.id, document_id=doc.id)
        db_session.add(commitment)
        await db_session.commit()

        result = await db_session.execute(
            select(Commitment).where(Commitment.id == commitment.id)
        )
        fetched = result.scalar_one()
        assert fetched.document_id == doc.id

    async def test_filter_pending_commitments(self, db_session: AsyncSession) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        c1 = make_commitment(user_id=user.id, commitment_text="Pending one")
        c2 = make_commitment(
            user_id=user.id,
            commitment_text="Done one",
            status=CommitmentStatus.COMPLETED,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        result = await db_session.execute(
            select(Commitment).where(
                Commitment.user_id == user.id,
                Commitment.status == CommitmentStatus.PENDING,
            )
        )
        pending = result.scalars().all()
        assert len(pending) == 1
        assert pending[0].commitment_text == "Pending one"
