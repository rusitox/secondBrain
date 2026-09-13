"""Unit tests for retrieval search and filters."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.retrieval.filters import SearchFilters
from app.services.retrieval.search import (
    SearchResult,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K,
    RECENCY_CANDIDATE_POOL,
    semantic_search,
)


class TestSearchFilters:
    """Tests for SearchFilters dataclass."""

    def test_defaults(self) -> None:
        f = SearchFilters()
        assert f.date_from is None
        assert f.date_to is None
        assert f.source is None
        assert f.sources == []
        assert f.author is None

    def test_with_all_fields(self) -> None:
        from datetime import datetime
        dt = datetime(2025, 1, 1)
        f = SearchFilters(
            date_from=dt,
            date_to=dt,
            source="slack",
            sources=["slack", "email"],
            author="alice",
        )
        assert f.date_from == dt
        assert f.date_to == dt
        assert f.source == "slack"
        assert f.sources == ["slack", "email"]
        assert f.author == "alice"


class TestSearchResult:
    """Tests for SearchResult model."""

    def test_to_dict(self) -> None:
        doc_id = uuid.uuid4()
        r = SearchResult(
            document_id=doc_id,
            content="hello world",
            source="slack",
            source_id="msg:123",
            metadata={"author": "bob"},
            similarity=0.95,
        )
        d = r.to_dict()
        assert d["document_id"] == str(doc_id)
        assert d["content"] == "hello world"
        assert d["source"] == "slack"
        assert d["source_id"] == "msg:123"
        assert d["metadata"] == {"author": "bob"}
        assert d["similarity"] == 0.95

    def test_similarity_rounding(self) -> None:
        r = SearchResult(
            document_id=uuid.uuid4(),
            content="test",
            source="email",
            source_id="e1",
            metadata={},
            similarity=0.87654321,
        )
        # similarity is stored as-is on the object
        assert r.similarity == 0.87654321


class TestRecencyKey:
    """Tests for SearchResult.recency_key(), which backs sort="recent"."""

    def test_uses_metadata_timestamp_when_present(self) -> None:
        r = SearchResult(
            document_id=uuid.uuid4(), content="x", source="slack", source_id="s1",
            metadata={"timestamp": "2026-06-01T10:00:00Z"}, similarity=0.5,
            _fallback_timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        assert r.recency_key() == datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_falls_back_to_created_at_when_metadata_timestamp_missing(self) -> None:
        fallback = datetime(2026, 3, 1, tzinfo=timezone.utc)
        r = SearchResult(
            document_id=uuid.uuid4(), content="x", source="slack", source_id="s1",
            metadata={}, similarity=0.5, _fallback_timestamp=fallback,
        )
        assert r.recency_key() == fallback

    def test_falls_back_when_metadata_timestamp_unparseable(self) -> None:
        fallback = datetime(2026, 3, 1, tzinfo=timezone.utc)
        r = SearchResult(
            document_id=uuid.uuid4(), content="x", source="slack", source_id="s1",
            metadata={"timestamp": "not-a-date"}, similarity=0.5, _fallback_timestamp=fallback,
        )
        assert r.recency_key() == fallback

    def test_naive_fallback_is_normalized_to_utc(self) -> None:
        """SQLite doesn't preserve tzinfo — a naive fallback must not crash
        comparisons against timezone-aware metadata-derived keys."""
        r = SearchResult(
            document_id=uuid.uuid4(), content="x", source="slack", source_id="s1",
            metadata={}, similarity=0.5, _fallback_timestamp=datetime(2026, 3, 1),
        )
        key = r.recency_key()
        assert key.tzinfo is not None
        other = SearchResult(
            document_id=uuid.uuid4(), content="y", source="slack", source_id="s2",
            metadata={"timestamp": "2026-06-01T00:00:00Z"}, similarity=0.5,
        )
        assert sorted([r, other], key=lambda x: x.recency_key())[-1] is other

    def test_defaults_to_min_when_nothing_available(self) -> None:
        r = SearchResult(
            document_id=uuid.uuid4(), content="x", source="slack", source_id="s1",
            metadata={}, similarity=0.5,
        )
        assert r.recency_key() == datetime.min.replace(tzinfo=timezone.utc)


def _make_doc(
    content: str, metadata: dict, created_at: datetime, doc_id: uuid.UUID = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id or uuid.uuid4()
    doc.content = content
    doc.source = "slack"
    doc.source_id = content
    doc.metadata_ = metadata
    doc.created_at = created_at
    return doc


class TestSemanticSearchSort:
    """semantic_search's sort="recent" re-ranking, exercised against a
    mocked db.execute (pgvector's cosine_distance isn't available under
    SQLite, so the query itself is never actually run — only the
    threshold-filter-then-sort logic in semantic_search is under test)."""

    @pytest.mark.asyncio
    async def test_relevance_sort_keeps_similarity_order(self) -> None:
        old_but_similar = _make_doc(
            "old", {"timestamp": "2020-01-01T00:00:00Z"}, datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        new_but_less_similar = _make_doc(
            "new", {"timestamp": "2026-06-01T00:00:00Z"}, datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        # distance 0.1 -> similarity 0.9 (old_but_similar); distance 0.2 -> similarity 0.8
        mock_result = MagicMock()
        mock_result.all.return_value = [(old_but_similar, 0.1), (new_but_less_similar, 0.2)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        embedder = AsyncMock()
        embedder.embed_single = AsyncMock(return_value=[0.1] * 1536)

        results = await semantic_search(db, embedder, uuid.uuid4(), "query", sort="relevance")

        assert [r.content for r in results] == ["old", "new"]

    @pytest.mark.asyncio
    async def test_recent_sort_reorders_by_timestamp(self) -> None:
        old_but_similar = _make_doc(
            "old", {"timestamp": "2020-01-01T00:00:00Z"}, datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        new_but_less_similar = _make_doc(
            "new", {"timestamp": "2026-06-01T00:00:00Z"}, datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [(old_but_similar, 0.1), (new_but_less_similar, 0.2)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        embedder = AsyncMock()
        embedder.embed_single = AsyncMock(return_value=[0.1] * 1536)

        results = await semantic_search(db, embedder, uuid.uuid4(), "query", sort="recent")

        assert [r.content for r in results] == ["new", "old"]

    @pytest.mark.asyncio
    async def test_recent_sort_widens_candidate_pool_and_trims_to_top_k(self) -> None:
        """A widened candidate LIMIT is used for sort="recent" so a recent-
        but-moderately-similar doc outside the plain top-K can surface, but
        the final result is still trimmed back down to top_k."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        embedder = AsyncMock()
        embedder.embed_single = AsyncMock(return_value=[0.1] * 1536)

        await semantic_search(db, embedder, uuid.uuid4(), "query", top_k=3, sort="recent")

        executed_stmt = db.execute.call_args[0][0]
        assert executed_stmt._limit_clause.value == RECENCY_CANDIDATE_POOL

    @pytest.mark.asyncio
    async def test_relevance_sort_uses_top_k_as_the_limit(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        embedder = AsyncMock()
        embedder.embed_single = AsyncMock(return_value=[0.1] * 1536)

        await semantic_search(db, embedder, uuid.uuid4(), "query", top_k=3, sort="relevance")

        executed_stmt = db.execute.call_args[0][0]
        assert executed_stmt._limit_clause.value == 3


class TestConstants:
    """Tests for search module constants."""

    def test_default_threshold(self) -> None:
        assert DEFAULT_SIMILARITY_THRESHOLD == 0.3

    def test_default_top_k(self) -> None:
        assert DEFAULT_TOP_K == 10
