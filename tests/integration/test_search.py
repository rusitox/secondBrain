"""Integration tests for search-related DB operations.

Uses SQLite to test document insertion and retrieval.
Note: pgvector cosine_distance is not available in SQLite,
so full semantic_search() is tested at e2e level with mocks.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.filters import SearchFilters
from app.services.retrieval.search import SearchResult


def _fake_embedding(dim: int = 1536, val: float = 0.1) -> List[float]:
    """Generate a fake embedding vector."""
    return [val] * dim


async def _ensure_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Insert a user row if it doesn't exist (required for FK)."""
    await db.execute(text(
        "INSERT OR IGNORE INTO users (id, email, full_name) VALUES (:id, :email, :name)"
    ), {"id": str(user_id), "email": f"{user_id}@test.com", "name": "Test User"})
    await db.flush()


async def _insert_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    source: str = "test",
    source_id: str = "",
    metadata: dict = None,
    embedding_val: float = 0.1,
) -> uuid.UUID:
    """Insert a document directly into the DB for testing."""
    await _ensure_user(db, user_id)

    doc_id = uuid.uuid4()
    meta_json = json.dumps(metadata or {})
    emb_json = json.dumps(_fake_embedding(1536, embedding_val))

    await db.execute(text(
        "INSERT INTO documents (id, user_id, content, embedding, source, source_id, metadata) "
        "VALUES (:id, :user_id, :content, :emb, :source, :source_id, :meta)"
    ), {
        "id": str(doc_id),
        "user_id": str(user_id),
        "content": content,
        "emb": emb_json,
        "source": source,
        "source_id": source_id,
        "meta": meta_json,
    })
    await db.flush()
    return doc_id


class TestDocumentStorage:
    """Integration tests for document storage used by search."""

    @pytest.mark.asyncio
    async def test_insert_and_read_document(self, db_session: AsyncSession) -> None:
        """Documents can be inserted and read back from SQLite."""
        user_id = uuid.uuid4()
        doc_id = await _insert_document(
            db_session, user_id, "Test document content",
            source="manual", source_id="m1",
            metadata={"author": "test"},
        )

        result = await db_session.execute(
            text("SELECT content, source, metadata FROM documents WHERE id = :id"),
            {"id": str(doc_id)},
        )
        row = result.first()
        assert row is not None
        assert row[0] == "Test document content"
        assert row[1] == "manual"
        meta = json.loads(row[2])
        assert meta["author"] == "test"

    @pytest.mark.asyncio
    async def test_unique_constraint(self, db_session: AsyncSession) -> None:
        """Duplicate (user_id, source, source_id) raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        user_id = uuid.uuid4()
        await _insert_document(
            db_session, user_id, "First",
            source="email", source_id="e1",
        )
        with pytest.raises(IntegrityError):
            await _insert_document(
                db_session, user_id, "Duplicate",
                source="email", source_id="e1",
            )

    @pytest.mark.asyncio
    async def test_multiple_sources(self, db_session: AsyncSession) -> None:
        """Documents from different sources for same user."""
        user_id = uuid.uuid4()
        await _insert_document(db_session, user_id, "Email content", source="email", source_id="e1")
        await _insert_document(db_session, user_id, "Slack content", source="slack", source_id="s1")
        await _insert_document(db_session, user_id, "Fathom content", source="fathom", source_id="f1")

        result = await db_session.execute(
            text("SELECT COUNT(*) FROM documents WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
        assert result.scalar() == 3

    @pytest.mark.asyncio
    async def test_user_isolation(self, db_session: AsyncSession) -> None:
        """Documents are isolated per user."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        await _insert_document(db_session, user_a, "User A doc", source="test", source_id="a1")
        await _insert_document(db_session, user_b, "User B doc", source="test", source_id="b1")

        result_a = await db_session.execute(
            text("SELECT content FROM documents WHERE user_id = :uid"),
            {"uid": str(user_a)},
        )
        rows_a = result_a.fetchall()
        assert len(rows_a) == 1
        assert rows_a[0][0] == "User A doc"


class TestSearchResultModel:
    """Tests for SearchResult data model."""

    def test_to_dict(self) -> None:
        doc_id = uuid.uuid4()
        r = SearchResult(
            document_id=doc_id,
            content="hello",
            source="slack",
            source_id="s1",
            metadata={"channel": "general"},
            similarity=0.85,
        )
        d = r.to_dict()
        assert d["document_id"] == str(doc_id)
        assert d["source"] == "slack"
        assert d["similarity"] == 0.85

    def test_search_result_is_dataclass(self) -> None:
        from dataclasses import is_dataclass
        assert is_dataclass(SearchResult)


class TestSearchFiltersModel:
    """Tests for SearchFilters construction."""

    def test_default_filters(self) -> None:
        f = SearchFilters()
        assert f.source is None
        assert f.sources == []
        assert f.author is None

    def test_filters_with_dates(self) -> None:
        f = SearchFilters(
            date_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2025, 12, 31, tzinfo=timezone.utc),
            source="email",
        )
        assert f.date_from.year == 2025
        assert f.source == "email"
