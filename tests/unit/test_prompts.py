"""Unit tests for RAG prompt templates."""
import pytest

from app.services.llm.prompts import (
    RAG_SYSTEM_PROMPT,
    build_context_block,
    format_rag_prompt,
)


class TestBuildContextBlock:
    """Tests for build_context_block."""

    def test_empty_sources(self) -> None:
        result = build_context_block([])
        assert "No relevant documents found" in result

    def test_single_source(self) -> None:
        sources = [
            {
                "content": "Meeting notes about Q3 goals",
                "source": "fathom",
                "metadata": {
                    "author": "alice@example.com",
                    "subject": "Q3 Planning",
                    "timestamp": "2025-01-15T10:00:00",
                },
            }
        ]
        result = build_context_block(sources)
        assert "[Source 1]" in result
        assert "Platform: fathom" in result
        assert "From: alice@example.com" in result
        assert "Subject: Q3 Planning" in result
        assert "Date: 2025-01-15T10:00:00" in result
        assert "Meeting notes about Q3 goals" in result

    def test_multiple_sources(self) -> None:
        sources = [
            {"content": "First doc", "source": "slack", "metadata": {"channel": "general"}},
            {"content": "Second doc", "source": "email", "metadata": {"author": "bob"}},
        ]
        result = build_context_block(sources)
        assert "[Source 1]" in result
        assert "[Source 2]" in result
        assert "Platform: slack" in result
        assert "Channel: #general" in result
        assert "Platform: email" in result
        assert "From: bob" in result

    def test_minimal_metadata(self) -> None:
        sources = [{"content": "bare content", "source": "manual", "metadata": {}}]
        result = build_context_block(sources)
        assert "[Source 1]" in result
        assert "Platform: manual" in result
        assert "bare content" in result

    def test_missing_source_key(self) -> None:
        sources = [{"content": "no source key", "metadata": {}}]
        result = build_context_block(sources)
        assert "Platform: unknown" in result


class TestFormatRagPrompt:
    """Tests for format_rag_prompt."""

    def test_formats_question_and_context(self) -> None:
        sources = [{"content": "Some fact", "source": "email", "metadata": {}}]
        result = format_rag_prompt("What happened?", sources)
        assert "Question: What happened?" in result
        assert "Some fact" in result
        assert "Context from your personal knowledge base:" in result

    def test_empty_sources(self) -> None:
        result = format_rag_prompt("Anything?", [])
        assert "No relevant documents found" in result
        assert "Question: Anything?" in result

    def test_curly_braces_in_question(self) -> None:
        """Curly braces in user input don't crash the prompt builder."""
        result = format_rag_prompt("What is {__class__}?", [])
        assert "{__class__}" in result

    def test_curly_braces_in_content(self) -> None:
        """Curly braces in document content don't crash the prompt builder."""
        sources = [{"content": "Config: {key: value}", "source": "slack", "metadata": {}}]
        result = format_rag_prompt("test?", sources)
        assert "{key: value}" in result


class TestRagSystemPrompt:
    """Tests for the RAG system prompt."""

    def test_contains_key_instructions(self) -> None:
        assert "ONLY" in RAG_SYSTEM_PROMPT
        assert "context" in RAG_SYSTEM_PROMPT.lower()
        assert "sources" in RAG_SYSTEM_PROMPT.lower()

    def test_contains_language_instruction(self) -> None:
        assert "same language" in RAG_SYSTEM_PROMPT
