"""Integration tests for commitment detection in the ingestion pipeline.

Tests the pipeline with a mocked CommitmentDetector to verify
the detection step integrates correctly with document creation.
"""
import uuid
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment, CommitmentStatus
from app.services.commitments.detector import CommitmentDetector, DetectedCommitment
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.pipeline import IngestionPipeline, IngestionResult
from tests.factories import make_user


def _fake_embedding(dim: int = 1536) -> List[float]:
    return [0.1] * dim


@pytest.fixture
def mock_embed():
    """Patch embedder to return fake embeddings."""
    async def _embed_texts(texts: List[str]) -> List[List[float]]:
        return [_fake_embedding() for _ in texts]

    with patch.object(Embedder, "embed_texts", side_effect=_embed_texts) as mock:
        yield mock


@pytest.fixture
def mock_detector() -> AsyncMock:
    """Mock CommitmentDetector that returns no commitments by default."""
    detector = AsyncMock(spec=CommitmentDetector)
    detector.detect_and_store = AsyncMock(return_value=[])
    return detector


class TestPipelineWithCommitmentDetection:
    """Integration tests for pipeline + commitment detection."""

    @pytest.mark.asyncio
    async def test_pipeline_without_detector(
        self, db_session: AsyncSession, mock_embed,
    ) -> None:
        """Pipeline works fine without commitment detector."""
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        pipeline = IngestionPipeline(embedder=Embedder(api_key="test"))
        result = await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="Just a normal document",
            source="test",
            source_id="t1",
        )
        await db_session.commit()
        assert result.documents_created == 1
        assert result.commitments_detected == 0

    @pytest.mark.asyncio
    async def test_pipeline_calls_detector_on_new_docs(
        self, db_session: AsyncSession, mock_embed, mock_detector: AsyncMock,
    ) -> None:
        """Pipeline calls commitment detector for new documents."""
        user = make_user(email="detector-test@test.com")
        db_session.add(user)
        await db_session.commit()

        pipeline = IngestionPipeline(
            embedder=Embedder(api_key="test"),
            commitment_detector=mock_detector,
        )
        result = await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="I'll send the report by Friday",
            source="email",
            source_id="e1",
            metadata={"timestamp": "2025-03-10T14:00:00"},
        )
        await db_session.commit()
        assert result.documents_created == 1
        mock_detector.detect_and_store.assert_called_once()
        call_kwargs = mock_detector.detect_and_store.call_args.kwargs
        assert call_kwargs["user_id"] == user.id
        assert call_kwargs["timestamp"] == "2025-03-10T14:00:00"

    @pytest.mark.asyncio
    async def test_pipeline_skips_detector_on_update(
        self, db_session: AsyncSession, mock_embed, mock_detector: AsyncMock,
    ) -> None:
        """Pipeline does NOT call detector when updating existing documents."""
        user = make_user(email="skip-test@test.com")
        db_session.add(user)
        await db_session.commit()

        pipeline = IngestionPipeline(
            embedder=Embedder(api_key="test"),
            commitment_detector=mock_detector,
        )

        # First ingestion: creates document
        await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="I'll send the report",
            source="email",
            source_id="e1",
        )
        await db_session.commit()
        mock_detector.detect_and_store.reset_mock()

        # Second ingestion: updates document (same source_id)
        result = await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="Updated: I'll send the report tomorrow",
            source="email",
            source_id="e1",
        )
        await db_session.commit()
        assert result.documents_updated == 1
        mock_detector.detect_and_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_counts_detected_commitments(
        self, db_session: AsyncSession, mock_embed,
    ) -> None:
        """Pipeline result includes commitment count."""
        user = make_user(email="count-test@test.com")
        db_session.add(user)
        await db_session.commit()

        # Create a mock detector that returns mock commitments
        mock_detector = AsyncMock(spec=CommitmentDetector)
        mock_commitment = MagicMock()
        mock_detector.detect_and_store = AsyncMock(
            return_value=[mock_commitment, mock_commitment]  # 2 commitments
        )

        pipeline = IngestionPipeline(
            embedder=Embedder(api_key="test"),
            commitment_detector=mock_detector,
        )
        result = await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="Action items: do X and do Y",
            source="slack",
            source_id="s1",
        )
        await db_session.commit()
        assert result.commitments_detected == 2

    @pytest.mark.asyncio
    async def test_ingestion_result_to_dict_includes_commitments(self) -> None:
        """IngestionResult.to_dict includes commitments_detected."""
        result = IngestionResult()
        result.documents_created = 1
        result.commitments_detected = 3
        d = result.to_dict()
        assert d["commitments_detected"] == 3
        assert d["documents_created"] == 1


class TestPendingOverdueEndpoints:
    """Integration tests for /commitments/filter/pending and /commitments/filter/overdue."""

    @pytest.mark.asyncio
    async def test_pending_endpoint(self, client) -> None:
        """GET /commitments/filter/pending returns only pending commitments."""
        # First create a user
        user_id = str(uuid.uuid4())
        resp = await client.post("/users/", json={
            "email": f"pending-test-{user_id[:8]}@test.com",
            "full_name": "Pending Test",
        })
        assert resp.status_code == 201
        real_user_id = resp.json()["id"]

        # Create a commitment
        resp = await client.post("/commitments/", json={
            "user_id": real_user_id,
            "commitment_text": "Send report",
            "priority": 2,
        }, headers={"X-User-Id": real_user_id})
        assert resp.status_code == 201

        # Check pending
        resp = await client.get(
            "/commitments/filter/pending",
            headers={"X-User-Id": real_user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(c["status"] == "pending" for c in data)

    @pytest.mark.asyncio
    async def test_overdue_endpoint_no_results(self, client) -> None:
        """GET /commitments/filter/overdue returns empty when no overdue items."""
        user_id = str(uuid.uuid4())
        resp = await client.post("/users/", json={
            "email": f"overdue-test-{user_id[:8]}@test.com",
            "full_name": "Overdue Test",
        })
        real_user_id = resp.json()["id"]

        # Create a commitment with no due date
        await client.post("/commitments/", json={
            "user_id": real_user_id,
            "commitment_text": "No deadline task",
        }, headers={"X-User-Id": real_user_id})

        resp = await client.get(
            "/commitments/filter/overdue",
            headers={"X-User-Id": real_user_id},
        )
        assert resp.status_code == 200
        # No due date = not overdue (nullslast puts them at end, but due_before filters them out)
        data = resp.json()
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_overdue_endpoint_with_past_due_date(self, client) -> None:
        """GET /commitments/filter/overdue returns items past their due date."""
        user_id = str(uuid.uuid4())
        resp = await client.post("/users/", json={
            "email": f"overdue2-{user_id[:8]}@test.com",
            "full_name": "Overdue Test 2",
        })
        real_user_id = resp.json()["id"]

        # Create a commitment with a past due date
        await client.post("/commitments/", json={
            "user_id": real_user_id,
            "commitment_text": "Past deadline task",
            "due_date": "2020-01-01T00:00:00Z",
        }, headers={"X-User-Id": real_user_id})

        resp = await client.get(
            "/commitments/filter/overdue",
            headers={"X-User-Id": real_user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["commitment_text"] == "Past deadline task"

    @pytest.mark.asyncio
    async def test_pending_requires_auth(self, client) -> None:
        resp = await client.get("/commitments/filter/pending")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_overdue_requires_auth(self, client) -> None:
        resp = await client.get("/commitments/filter/overdue")
        assert resp.status_code == 401
