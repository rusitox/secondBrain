"""Async multi-provider LLM client with retry.

Supports Anthropic and OpenAI (including OpenAI-compatible APIs)
by setting LLM_MODEL to the appropriate provider/model string.

Examples:
    anthropic/claude-haiku-4-5-20251001
    openai/gpt-4o-mini
    openai/gemini-2.0-flash  (via base_url override)
"""
import asyncio
import logging
from typing import Optional

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
MAX_TOKENS = 2048
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds


def _parse_provider(model: str) -> tuple:
    """Parse 'provider/model-name' into (provider, model_id).

    If no provider prefix, assumes 'anthropic'.
    """
    if "/" in model:
        provider, model_id = model.split("/", 1)
        return provider.lower(), model_id
    return "anthropic", model


class LLMClient:
    """Async LLM wrapper supporting multiple providers."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = MAX_TOKENS,
        base_url: Optional[str] = None,
    ) -> None:
        self._provider, self._model_id = _parse_provider(model)
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._base_url = base_url

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """Generate a response from the configured LLM.

        Returns the text content of the response.
        """
        if self._provider == "anthropic":
            return await self._generate_anthropic(
                system_prompt, user_message, temperature
            )
        else:
            return await self._generate_openai(
                system_prompt, user_message, temperature
            )

    async def _generate_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Generate using the Anthropic SDK."""
        client = AsyncAnthropic(api_key=self._api_key)
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.messages.create(
                    model=self._model_id,
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    temperature=temperature,
                )
                if response.content:
                    block = response.content[0]
                    return getattr(block, "text", "")
                return ""
            except RateLimitError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            except APIStatusError as e:
                last_error = e
                if e.status_code >= 500:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "LLM server error %d (attempt %d/%d), retrying in %.1fs",
                        e.status_code, attempt + 1, MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM API call failed after retries")

    async def _generate_openai(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Generate using the OpenAI SDK (works with any OpenAI-compatible API)."""
        from openai import RateLimitError as OpenAIRateLimitError
        from openai import APIStatusError as OpenAIAPIStatusError

        client = AsyncOpenAI(
            api_key=self._api_key or "not-set",
            base_url=self._base_url,
        )
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.chat.completions.create(
                    model=self._model_id,
                    max_tokens=self._max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                return content or ""
            except OpenAIRateLimitError as e:
                last_error = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            except OpenAIAPIStatusError as e:
                last_error = e
                if e.status_code >= 500:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "LLM server error %d (attempt %d/%d), retrying in %.1fs",
                        e.status_code, attempt + 1, MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM API call failed after retries")


# Backward-compatible alias
ClaudeClient = LLMClient
