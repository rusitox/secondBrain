"""Async Claude client with retry for RAG and agent queries.

Wraps the Anthropic SDK with exponential backoff for rate limits
and transient server errors.
"""
import asyncio
import logging
from typing import List, Optional

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds


class ClaudeClient:
    """Async wrapper around the Anthropic API with retry logic."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """Generate a response from Claude.

        Returns the text content of the first response block.
        """
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                )
                # Extract text from the first content block
                if response.content:
                    return response.content[0].text
                return ""
            except RateLimitError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Claude rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            except APIStatusError as e:
                last_error = e
                if e.status_code >= 500:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Claude server error %d (attempt %d/%d), retrying in %.1fs",
                        e.status_code, attempt + 1, MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude API call failed after retries")
