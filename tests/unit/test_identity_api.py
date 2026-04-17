"""Unit tests for identity schemas and stats schema."""
import uuid
from datetime import datetime, timezone

from app.api.schemas.identity import IdentityCreate, IdentityRead, IdentityUpdate, UserStats


class TestIdentityCreate:
    def test_defaults(self) -> None:
        data = IdentityCreate()
        assert data.persona_description == ""
        assert data.tone_guidelines == ""
        assert data.heuristics == {}

    def test_with_values(self) -> None:
        data = IdentityCreate(
            persona_description="CTO at startup",
            tone_guidelines="Direct and concise",
            heuristics={"urgent_means_sameday": True},
        )
        assert data.persona_description == "CTO at startup"
        assert data.heuristics["urgent_means_sameday"] is True


class TestIdentityUpdate:
    def test_all_none(self) -> None:
        data = IdentityUpdate()
        assert data.persona_description is None
        assert data.tone_guidelines is None
        assert data.heuristics is None

    def test_partial_update(self) -> None:
        data = IdentityUpdate(tone_guidelines="Be casual")
        assert data.persona_description is None
        assert data.tone_guidelines == "Be casual"


class TestIdentityRead:
    def test_from_dict(self) -> None:
        now = datetime.now(timezone.utc)
        data = IdentityRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            persona_description="Engineer",
            tone_guidelines="Technical",
            heuristics={"key": "value"},
            created_at=now,
            updated_at=now,
        )
        assert data.persona_description == "Engineer"
        assert data.heuristics == {"key": "value"}


class TestUserStats:
    def test_defaults(self) -> None:
        stats = UserStats(
            documents_total=0,
            commitments_pending=0,
            commitments_overdue=0,
            integrations_active=0,
            integrations_total=0,
        )
        assert stats.last_sync is None

    def test_with_values(self) -> None:
        now = datetime.now(timezone.utc)
        stats = UserStats(
            documents_total=100,
            commitments_pending=5,
            commitments_overdue=2,
            integrations_active=3,
            integrations_total=4,
            last_sync=now,
        )
        assert stats.documents_total == 100
        assert stats.last_sync == now
