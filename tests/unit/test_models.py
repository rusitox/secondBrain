"""Unit tests for Pydantic schemas validation."""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.schemas.user import UserCreate, UserRead, UserUpdate
from app.api.schemas.commitment import CommitmentCreate, CommitmentRead, CommitmentUpdate
from app.api.schemas.document import DocumentCreate, DocumentRead
from app.api.schemas.integration import IntegrationCreate, IntegrationRead, IntegrationUpdate
from app.models.commitment import CommitmentStatus
from app.models.integration import Platform


class TestUserSchemas:
    def test_user_create_valid(self) -> None:
        user = UserCreate(email="test@example.com", full_name="Test User")
        assert user.email == "test@example.com"
        assert user.timezone == "UTC"

    def test_user_create_invalid_email(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="not-an-email", full_name="Test")

    def test_user_create_missing_name(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(email="test@example.com")  # type: ignore[call-arg]

    def test_user_create_valid_timezone(self) -> None:
        user = UserCreate(
            email="test@example.com",
            full_name="Test",
            timezone="America/Argentina/Buenos_Aires",
        )
        assert user.timezone == "America/Argentina/Buenos_Aires"

    def test_user_create_invalid_timezone(self) -> None:
        with pytest.raises(ValidationError, match="Invalid timezone"):
            UserCreate(
                email="test@example.com",
                full_name="Test",
                timezone="banana",
            )

    def test_user_update_partial(self) -> None:
        update = UserUpdate(full_name="New Name")
        assert update.full_name == "New Name"
        assert update.timezone is None

    def test_user_update_invalid_timezone(self) -> None:
        with pytest.raises(ValidationError, match="Invalid timezone"):
            UserUpdate(timezone="Not/A/Timezone")

    def test_user_read_from_attributes(self) -> None:
        user = UserRead(
            id=uuid.uuid4(),
            email="test@example.com",
            full_name="Test",
            timezone="UTC",
            created_at=datetime.now(timezone.utc),
        )
        assert user.email == "test@example.com"


class TestCommitmentSchemas:
    def test_commitment_create_valid(self) -> None:
        c = CommitmentCreate(
            user_id=uuid.uuid4(),
            commitment_text="Send report",
        )
        assert c.priority == 3
        assert c.document_id is None

    def test_commitment_create_priority_bounds(self) -> None:
        with pytest.raises(ValidationError):
            CommitmentCreate(
                user_id=uuid.uuid4(),
                commitment_text="Test",
                priority=0,
            )
        with pytest.raises(ValidationError):
            CommitmentCreate(
                user_id=uuid.uuid4(),
                commitment_text="Test",
                priority=6,
            )

    def test_commitment_update_status(self) -> None:
        update = CommitmentUpdate(status=CommitmentStatus.COMPLETED)
        assert update.status == CommitmentStatus.COMPLETED

    def test_commitment_read(self) -> None:
        now = datetime.now(timezone.utc)
        c = CommitmentRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            document_id=None,
            commitment_text="Do something",
            due_date=None,
            status=CommitmentStatus.PENDING,
            priority=3,
            created_at=now,
            updated_at=now,
        )
        assert c.status == CommitmentStatus.PENDING


class TestDocumentSchemas:
    def test_document_create_valid(self) -> None:
        doc = DocumentCreate(
            user_id=uuid.uuid4(),
            content="Hello world",
            source="slack",
        )
        assert doc.metadata_ == {}
        assert doc.source_id == ""

    def test_document_create_with_metadata(self) -> None:
        doc = DocumentCreate(
            user_id=uuid.uuid4(),
            content="Hello",
            source="outlook",
            metadata_={"author": "John", "thread_id": "abc"},
        )
        assert doc.metadata_["author"] == "John"

    def test_document_create_source_max_length(self) -> None:
        with pytest.raises(ValidationError):
            DocumentCreate(
                user_id=uuid.uuid4(),
                content="Hello",
                source="a" * 21,  # exceeds max_length=20
            )

    def test_document_create_metadata_default_independent(self) -> None:
        """Verify that default metadata dicts are independent instances."""
        doc1 = DocumentCreate(user_id=uuid.uuid4(), content="A", source="slack")
        doc2 = DocumentCreate(user_id=uuid.uuid4(), content="B", source="slack")
        doc1.metadata_["key"] = "value"
        assert "key" not in doc2.metadata_

    def test_document_read(self) -> None:
        doc = DocumentRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            content="Content",
            source="teams",
            source_id="msg-123",
            created_at=datetime.now(timezone.utc),
        )
        assert doc.source == "teams"


class TestIntegrationSchemas:
    def test_integration_create_valid(self) -> None:
        i = IntegrationCreate(
            user_id=uuid.uuid4(),
            platform=Platform.SLACK,
            access_token="xoxb-token",
        )
        assert i.refresh_token == ""

    def test_integration_create_all_platforms(self) -> None:
        for platform in Platform:
            i = IntegrationCreate(
                user_id=uuid.uuid4(),
                platform=platform,
                access_token="token",
            )
            assert i.platform == platform

    def test_integration_read_no_tokens(self) -> None:
        """IntegrationRead should not expose tokens."""
        now = datetime.now(timezone.utc)
        i = IntegrationRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            platform=Platform.OUTLOOK,
            last_sync_at=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert not hasattr(i, "access_token")
        assert not hasattr(i, "refresh_token")

    def test_integration_update(self) -> None:
        update = IntegrationUpdate(is_active=False)
        assert update.is_active is False
        assert update.access_token is None
