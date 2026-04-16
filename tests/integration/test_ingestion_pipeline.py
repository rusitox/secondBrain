"""Integration tests for the ingestion pipeline (embedder mocked)."""
import uuid
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.pipeline import IngestionPipeline
from tests.factories import make_user


def _fake_embedding(dim: int = 1536) -> List[float]:
    return [0.1] * dim


@pytest.fixture
def pipeline() -> IngestionPipeline:
    embedder = Embedder(api_key="test-key")
    return IngestionPipeline(embedder=embedder)


@pytest.fixture
def mock_embed():
    """Patch embedder to return fake embeddings."""
    async def _embed_texts(texts: List[str]) -> List[List[float]]:
        return [_fake_embedding() for _ in texts]

    with patch.object(Embedder, "embed_texts", side_effect=_embed_texts) as mock:
        yield mock


class TestIngestionPipeline:
    async def test_ingest_raw_creates_document(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        result = await pipeline.ingest_raw(
            db=db_session,
            user_id=user.id,
            content="Meeting notes: we agreed on the budget.",
            source="slack",
            source_id="msg-001",
            metadata={"author": "alice"},
        )
        await db_session.commit()

        assert result.documents_created == 1
        assert result.documents_skipped == 0
        assert result.chunks_total == 1

        # Verify in DB
        docs = await db_session.execute(
            select(Document).where(Document.user_id == user.id)
        )
        doc = docs.scalar_one()
        assert "agreed on the budget" in doc.content
        assert doc.source == "slack"
        assert doc.source_id == "msg-001"

    async def test_ingest_raw_deduplicates(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        """Re-ingesting same source_id should update, not duplicate."""
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        # First ingest
        await pipeline.ingest_raw(
            db=db_session, user_id=user.id,
            content="Original content", source="email", source_id="email-001",
        )
        await db_session.commit()

        # Re-ingest same source_id with updated content
        result = await pipeline.ingest_raw(
            db=db_session, user_id=user.id,
            content="Updated content", source="email", source_id="email-001",
        )
        await db_session.commit()

        assert result.documents_updated == 1
        assert result.documents_created == 0

        # Only one document in DB
        docs = await db_session.execute(
            select(Document).where(Document.user_id == user.id)
        )
        all_docs = docs.scalars().all()
        assert len(all_docs) == 1
        assert "Updated content" in all_docs[0].content

    async def test_ingest_raw_skips_empty_content(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        result = await pipeline.ingest_raw(
            db=db_session, user_id=user.id,
            content="", source="slack", source_id="empty",
        )
        assert result.documents_skipped == 1
        assert result.documents_created == 0

    async def test_ingest_raw_long_text_creates_chunks(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        """Long text should be split into multiple document chunks."""
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        long_text = "This is a detailed discussion. " * 200  # ~6200 chars
        result = await pipeline.ingest_raw(
            db=db_session, user_id=user.id,
            content=long_text, source="fathom", source_id="rec-001",
        )
        await db_session.commit()

        assert result.chunks_total > 1
        assert result.documents_created == result.chunks_total

        # Verify multiple docs with chunked source_ids
        docs = await db_session.execute(
            select(Document).where(Document.user_id == user.id)
        )
        all_docs = docs.scalars().all()
        assert len(all_docs) > 1
        source_ids = [d.source_id for d in all_docs]
        assert any("#chunk" in sid for sid in source_ids)

    async def test_ingest_batch(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        items = [
            {"content": "First message.", "source_id": "msg-1", "metadata": {"author": "A"}},
            {"content": "Second message.", "source_id": "msg-2", "metadata": {"author": "B"}},
            {"content": "Third message.", "source_id": "msg-3"},
        ]
        result = await pipeline.ingest_batch(
            db=db_session, user_id=user.id, items=items, source="slack",
        )
        await db_session.commit()

        assert result.documents_created == 3
        assert result.chunks_total == 3

    async def test_ingest_preserves_metadata(
        self, db_session: AsyncSession, pipeline: IngestionPipeline, mock_embed,
    ) -> None:
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        metadata = {"author": "alice@corp.com", "thread_id": "t-123", "project_id": "P1"}
        await pipeline.ingest_raw(
            db=db_session, user_id=user.id,
            content="Important note.", source="slack", source_id="meta-test",
            metadata=metadata,
        )
        await db_session.commit()

        docs = await db_session.execute(
            select(Document).where(Document.source_id == "meta-test")
        )
        doc = docs.scalar_one()
        assert doc.metadata_["author"] == "alice@corp.com"
        assert doc.metadata_["thread_id"] == "t-123"
