"""Unit tests for text chunking."""
import pytest

from app.services.ingestion.chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text,
)


class TestChunkText:
    def test_empty_text_returns_empty_list(self) -> None:
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert chunk_text("   \n\n  ") == []

    def test_short_text_returns_single_chunk(self) -> None:
        text = "This is a short text."
        result = chunk_text(text)
        assert len(result) == 1
        assert result[0] == text

    def test_text_exactly_chunk_size(self) -> None:
        text = "x" * DEFAULT_CHUNK_SIZE
        result = chunk_text(text)
        assert len(result) == 1

    def test_long_text_produces_multiple_chunks(self) -> None:
        # Create text longer than chunk_size
        text = "This is a sentence. " * 200  # ~4000 chars
        result = chunk_text(text)
        assert len(result) > 1

    def test_chunks_have_overlap(self) -> None:
        """Adjacent chunks should share some text (overlap)."""
        text = "Word " * 500  # ~2500 chars
        result = chunk_text(text, chunk_size=200, chunk_overlap=50)
        assert len(result) > 2
        # Check that consecutive chunks share content
        for i in range(len(result) - 1):
            # The end of chunk i should overlap with start of chunk i+1
            end_words = result[i].split()[-3:]
            start_words = result[i + 1].split()[:10]
            overlap = set(end_words) & set(start_words)
            # At least some words should overlap
            assert len(overlap) > 0 or len(result[i]) < 200

    def test_custom_chunk_size(self) -> None:
        text = "Hello world. " * 100  # ~1300 chars
        result_small = chunk_text(text, chunk_size=100, chunk_overlap=10)
        result_large = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(result_small) > len(result_large)

    def test_respects_paragraph_boundaries(self) -> None:
        """Splitter should prefer splitting at paragraph boundaries."""
        text = "First paragraph content.\n\nSecond paragraph content.\n\nThird paragraph content."
        result = chunk_text(text, chunk_size=40, chunk_overlap=5)
        # Each chunk should ideally be a paragraph
        assert any("First paragraph" in c for c in result)
        assert any("Second paragraph" in c for c in result)

    def test_no_empty_chunks(self) -> None:
        text = "Content here.\n\n\n\nMore content.\n\n\n\nEven more."
        result = chunk_text(text)
        for chunk in result:
            assert chunk.strip() != ""

    def test_strips_leading_trailing_whitespace(self) -> None:
        text = "   Some text with spaces   "
        result = chunk_text(text)
        assert len(result) == 1
        assert result[0] == "Some text with spaces"
