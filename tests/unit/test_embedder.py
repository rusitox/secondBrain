"""Unit tests for the embedder service."""
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ingestion.embedder import Embedder, MAX_BATCH_SIZE


def _make_embedding_response(texts: List[str]) -> MagicMock:
    """Create a mock OpenAI embedding response."""
    mock_resp = MagicMock()
    mock_resp.data = []
    for i, text in enumerate(texts):
        item = MagicMock()
        item.index = i
        item.embedding = [0.1 * (i + 1)] * 10  # simple distinguishable vectors
        mock_resp.data.append(item)
    return mock_resp


class TestEmbedder:
    @pytest.fixture
    def embedder(self) -> Embedder:
        return Embedder(api_key="test-key")

    async def test_embed_empty_list(self, embedder: Embedder) -> None:
        result = await embedder.embed_texts([])
        assert result == []

    async def test_embed_single_text(self, embedder: Embedder) -> None:
        mock_resp = _make_embedding_response(["hello"])
        with patch.object(embedder._client.embeddings, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_resp
            result = await embedder.embed_single("hello")
            assert len(result) == 10
            mock_create.assert_called_once()

    async def test_embed_multiple_texts(self, embedder: Embedder) -> None:
        texts = ["hello", "world", "test"]
        mock_resp = _make_embedding_response(texts)
        with patch.object(embedder._client.embeddings, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_resp
            result = await embedder.embed_texts(texts)
            assert len(result) == 3
            # Verify order preserved
            assert result[0] != result[1]

    async def test_embed_preserves_order_when_response_unordered(self, embedder: Embedder) -> None:
        """Response items may not be in order — embedder should sort by index."""
        mock_resp = MagicMock()
        # Return items out of order
        item0 = MagicMock()
        item0.index = 1
        item0.embedding = [0.2] * 10
        item1 = MagicMock()
        item1.index = 0
        item1.embedding = [0.1] * 10
        mock_resp.data = [item0, item1]

        with patch.object(embedder._client.embeddings, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_resp
            result = await embedder.embed_texts(["first", "second"])
            assert result[0] == [0.1] * 10  # index 0 first
            assert result[1] == [0.2] * 10  # index 1 second

    async def test_embed_batches_large_input(self, embedder: Embedder) -> None:
        """Input larger than MAX_BATCH_SIZE should be split into batches."""
        texts = [f"text_{i}" for i in range(MAX_BATCH_SIZE + 10)]

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            input_texts = kwargs["input"]
            return _make_embedding_response(input_texts)

        with patch.object(embedder._client.embeddings, "create", side_effect=mock_create):
            result = await embedder.embed_texts(texts)
            assert len(result) == MAX_BATCH_SIZE + 10
            assert call_count == 2  # one full batch + one partial

    async def test_embed_retries_on_rate_limit(self, embedder: Embedder) -> None:
        """Should retry with backoff on RateLimitError."""
        from openai import RateLimitError

        mock_resp = _make_embedding_response(["text"])
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429, headers={}),
                    body=None,
                )
            return mock_resp

        with patch.object(embedder._client.embeddings, "create", side_effect=mock_create):
            with patch("app.services.ingestion.embedder.asyncio.sleep", new_callable=AsyncMock):
                result = await embedder.embed_texts(["text"])
                assert len(result) == 1
                assert call_count == 2

    async def test_embed_raises_after_max_retries(self, embedder: Embedder) -> None:
        """Should raise after exhausting retries."""
        from openai import RateLimitError

        async def mock_create(**kwargs):
            raise RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            )

        with patch.object(embedder._client.embeddings, "create", side_effect=mock_create):
            with patch("app.services.ingestion.embedder.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RateLimitError):
                    await embedder.embed_texts(["text"])
