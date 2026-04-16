"""Text embedding via OpenAI API.

Supports batch embedding (up to 2048 texts per call) with
exponential backoff retry for rate limits and transient errors.
"""
import logging
import asyncio
from typing import List, Optional

from openai import AsyncOpenAI, RateLimitError, APIError

logger = logging.getLogger(__name__)

# OpenAI batch limit
MAX_BATCH_SIZE = 2048

# Retry config
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds

# Default model
DEFAULT_MODEL = "text-embedding-3-small"


class Embedder:
    """Async OpenAI embedder with batch support and retry."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, batching if necessary.

        Returns a list of embedding vectors (same order as input).
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i : i + MAX_BATCH_SIZE]
            embeddings = await self._embed_batch(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single text string."""
        result = await self.embed_texts([text])
        return result[0]

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a single batch with exponential backoff retry."""
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                )
                # Sort by index to ensure correct ordering
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return [item.embedding for item in sorted_data]
            except RateLimitError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Rate limited on embedding (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            except APIError as e:
                last_error = e
                if e.status_code and e.status_code >= 500:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "OpenAI server error %s (attempt %d/%d), retrying in %.1fs",
                        e.status_code, attempt + 1, MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Embedding failed after retries")
