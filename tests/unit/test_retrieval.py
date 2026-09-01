"""Unit tests for retrieval search and filters."""
import uuid

import pytest

from app.services.retrieval.filters import SearchFilters
from app.services.retrieval.search import SearchResult, DEFAULT_SIMILARITY_THRESHOLD, DEFAULT_TOP_K


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


class TestConstants:
    """Tests for search module constants."""

    def test_default_threshold(self) -> None:
        assert DEFAULT_SIMILARITY_THRESHOLD == 0.3

    def test_default_top_k(self) -> None:
        assert DEFAULT_TOP_K == 10
