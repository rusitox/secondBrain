"""End-to-end tests for cross-platform query endpoint.

Tests the full POST /query flow: request → embed → search → Claude → response.
All external services (OpenAI embeddings, Claude) are mocked.
"""
import uuid
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import app


def _fake_embedding(dim: int = 1536, val: float = 0.1) -> List[float]:
    return [val] * dim


class TestQueryEndpoint:
    """E2E tests for POST /query."""

    @pytest.mark.asyncio
    async def test_query_missing_auth(self, client: AsyncClient) -> None:
        """Query without X-User-Id returns 401."""
        resp = await client.post("/query", json={"question": "test?"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_query_empty_question(self, client: AsyncClient) -> None:
        """Empty question returns 422 validation error."""
        user_id = str(uuid.uuid4())
        resp = await client.post(
            "/query",
            json={"question": ""},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_query_no_results(self, client: AsyncClient) -> None:
        """Query with no matching documents returns empty sources + answer."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude:
            # Mock embedder
            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            # Mock semantic_search to return empty
            with patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = []

                # Mock Claude
                claude_client = AsyncMock()
                claude_client.generate = AsyncMock(
                    return_value="I don't have any relevant information in your knowledge base to answer that question."
                )
                mock_claude.return_value = claude_client

                resp = await client.post(
                    "/query",
                    json={"question": "What happened in last week's meeting?"},
                    headers={"X-User-Id": user_id},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []
        assert "don't have" in data["answer"] or len(data["answer"]) > 0
        assert data["query"] == "What happened in last week's meeting?"

    @pytest.mark.asyncio
    async def test_query_with_results(self, client: AsyncClient) -> None:
        """Query that finds documents returns answer with sources."""
        user_id = str(uuid.uuid4())

        from app.services.retrieval.search import SearchResult
        mock_results = [
            SearchResult(
                document_id=uuid.uuid4(),
                content="We discussed Q3 goals and decided to focus on growth.",
                source="fathom",
                source_id="f1",
                metadata={"author": "alice@example.com", "subject": "Q3 Planning"},
                similarity=0.92,
            ),
            SearchResult(
                document_id=uuid.uuid4(),
                content="Action item: prepare growth report by Friday.",
                source="slack",
                source_id="s1",
                metadata={"channel": "strategy", "author": "bob"},
                similarity=0.85,
            ),
        ]

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            mock_search.return_value = mock_results

            claude_client = AsyncMock()
            claude_client.generate = AsyncMock(
                return_value="In the Q3 planning meeting, the team decided to focus on growth. "
                "Bob has an action item to prepare the growth report by Friday."
            )
            mock_claude.return_value = claude_client

            resp = await client.post(
                "/query",
                json={
                    "question": "What are the Q3 goals?",
                    "top_k": 5,
                    "threshold": 0.5,
                },
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 2
        assert data["sources"][0]["source"] == "fathom"
        assert data["sources"][1]["source"] == "slack"
        assert "growth" in data["answer"].lower()
        assert data["query"] == "What are the Q3 goals?"

    @pytest.mark.asyncio
    async def test_query_with_filters(self, client: AsyncClient) -> None:
        """Query with filters passes them through to search."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            mock_search.return_value = []

            claude_client = AsyncMock()
            claude_client.generate = AsyncMock(return_value="No results.")
            mock_claude.return_value = claude_client

            resp = await client.post(
                "/query",
                json={
                    "question": "updates from slack?",
                    "source": "slack",
                    "author": "alice",
                    "date_from": "2025-01-01T00:00:00",
                },
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        # Verify filters were passed to semantic_search
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["filters"].source == "slack"
        assert call_kwargs["filters"].author == "alice"
        assert call_kwargs["filters"].date_from is not None

    @pytest.mark.asyncio
    async def test_query_claude_error_returns_502(self, client: AsyncClient) -> None:
        """When Claude API fails, endpoint returns 502."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            mock_search.return_value = []

            claude_client = AsyncMock()
            claude_client.generate = AsyncMock(side_effect=RuntimeError("API down"))
            mock_claude.return_value = claude_client

            resp = await client.post(
                "/query",
                json={"question": "test?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 502
        assert "Failed to generate answer" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_query_response_structure(self, client: AsyncClient) -> None:
        """Verify response matches QueryResponse schema exactly."""
        user_id = str(uuid.uuid4())

        from app.services.retrieval.search import SearchResult
        mock_results = [
            SearchResult(
                document_id=uuid.uuid4(),
                content="Some content",
                source="email",
                source_id="e1",
                metadata={"author": "test@test.com", "subject": "Test"},
                similarity=0.88,
            ),
        ]

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            mock_search.return_value = mock_results

            claude_client = AsyncMock()
            claude_client.generate = AsyncMock(return_value="Answer here")
            mock_claude.return_value = claude_client

            resp = await client.post(
                "/query",
                json={"question": "test query"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        # Verify all required fields
        assert "answer" in data
        assert "sources" in data
        assert "query" in data
        # Verify source structure
        src = data["sources"][0]
        assert "document_id" in src
        assert "content" in src
        assert "source" in src
        assert "source_id" in src
        assert "metadata" in src
        assert "similarity" in src

    @pytest.mark.asyncio
    async def test_query_source_and_sources_conflict(self, client: AsyncClient) -> None:
        """Providing both 'source' and 'sources' returns 422."""
        user_id = str(uuid.uuid4())
        resp = await client.post(
            "/query",
            json={
                "question": "test?",
                "source": "email",
                "sources": ["slack", "fathom"],
            },
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_query_with_curly_braces(self, client: AsyncClient) -> None:
        """Question with curly braces doesn't crash format_rag_prompt."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query._get_claude_client") as mock_claude, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            embedder.embed_single = AsyncMock(return_value=_fake_embedding())
            mock_emb.return_value = embedder

            mock_search.return_value = []

            claude_client = AsyncMock()
            claude_client.generate = AsyncMock(return_value="No info found.")
            mock_claude.return_value = claude_client

            resp = await client.post(
                "/query",
                json={"question": "What is {__class__} and {{nested}}?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "{__class__}" in data["query"]

    @pytest.mark.asyncio
    async def test_query_search_error_returns_503(self, client: AsyncClient) -> None:
        """When embedding/search fails, endpoint returns 503."""
        user_id = str(uuid.uuid4())

        with patch("app.api.routers.query._get_embedder") as mock_emb, \
             patch("app.api.routers.query.semantic_search", new_callable=AsyncMock) as mock_search:

            embedder = AsyncMock()
            mock_emb.return_value = embedder

            mock_search.side_effect = RuntimeError("Embedding API down")

            resp = await client.post(
                "/query",
                json={"question": "test?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 503
        assert "Search service" in resp.json()["detail"]
