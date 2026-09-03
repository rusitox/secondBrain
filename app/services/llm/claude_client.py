"""Async multi-provider LLM client with retry.

Supports Anthropic and OpenAI (including OpenAI-compatible APIs)
by setting LLM_MODEL to the appropriate provider/model string.

Examples:
    anthropic/claude-haiku-4-5-20251001
    openai/gpt-4o-mini
    openai/gemini-2.0-flash  (via base_url override)
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from anthropic import AsyncAnthropic, RateLimitError, APIStatusError
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
MAX_TOKENS = 2048
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds


@dataclass
class ToolCall:
    """Record of a single tool invocation within an agentic loop."""

    tool_name: str
    tool_input: Dict[str, Any]
    tool_result: str  # JSON string


@dataclass
class ToolUseResult:
    """Final result from an agentic tool-use loop."""

    final_answer: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    iterations: int = 0
    stop_reason: str = "end_turn"


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

    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executors: Dict[str, Callable],
        system: Optional[str] = None,
        max_iterations: int = 10,
        stream_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> ToolUseResult:
        """Run an agentic tool-use loop until a final answer is produced.

        Dispatches to the appropriate provider loop based on configured provider.
        When stream_callback is provided (Anthropic only), the final answer is
        streamed token-by-token via the callback. Tool-use iterations remain
        non-streaming for simplicity.
        """
        if self._provider == "anthropic":
            return await self._generate_with_tools_anthropic(
                messages, tools, tool_executors, system, max_iterations, stream_callback
            )
        else:
            # OpenAI streaming not yet implemented — stream_callback ignored
            return await self._generate_with_tools_openai(
                messages, tools, tool_executors, system, max_iterations
            )

    async def _call_anthropic_with_retry(
        self,
        model: str,
        max_tokens: int,
        system: Optional[str],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Any:
        """Call Anthropic messages.create with exponential-backoff retry."""
        client = AsyncAnthropic(api_key=self._api_key)
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if system is not None:
                    kwargs["system"] = system
                if tools:
                    kwargs["tools"] = tools
                return await client.messages.create(**kwargs)  # type: ignore[call-overload]
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

    async def _generate_with_tools_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executors: Dict[str, Callable],
        system: Optional[str],
        max_iterations: int,
        stream_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> ToolUseResult:
        """Anthropic agentic loop: call → tool_use → call → … → end_turn.

        Tool-use iterations use non-streaming calls. When stream_callback is
        provided, the final answer is produced via a streaming call so tokens
        are delivered to the caller incrementally.
        """
        tool_calls_made: List[ToolCall] = []
        current_messages = list(messages)
        iterations = 0

        while iterations < max_iterations:
            response = await self._call_anthropic_with_retry(
                model=self._model_id,
                max_tokens=self._max_tokens,
                system=system,
                messages=current_messages,
                tools=tools,
            )
            iterations += 1

            # Check whether any content block is a tool_use
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                # No tool call — this is the final answer turn.
                # If a stream_callback is provided, re-issue the same call as a
                # streaming request so tokens are delivered incrementally.
                if stream_callback is not None:
                    client = AsyncAnthropic(api_key=self._api_key)
                    stream_text_parts: List[str] = []
                    async with client.messages.stream(
                        model=self._model_id,
                        max_tokens=self._max_tokens,
                        system=system or "",
                        messages=current_messages,
                        tools=tools or [],
                    ) as stream:  # type: ignore[call-overload]
                        async for text_chunk in stream.text_stream:
                            await stream_callback(text_chunk)
                            stream_text_parts.append(text_chunk)
                    return ToolUseResult(
                        final_answer="".join(stream_text_parts),
                        tool_calls=tool_calls_made,
                        iterations=iterations,
                        stop_reason="end_turn",
                    )

                # Non-streaming path: extract text from the already-received response
                final_text = ""
                for block in response.content:
                    if block.type == "text":
                        final_text = getattr(block, "text", "")
                        break
                return ToolUseResult(
                    final_answer=final_text,
                    tool_calls=tool_calls_made,
                    iterations=iterations,
                    stop_reason="end_turn",
                )

            # Append the assistant turn with all content blocks
            current_messages.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            })

            # Execute each tool and collect results
            tool_results_content = []
            for block in tool_use_blocks:
                tool_name = block.name
                tool_input = block.input

                if tool_name not in tool_executors:
                    tool_result = "Error: unknown tool '%s'" % tool_name
                else:
                    try:
                        raw = await tool_executors[tool_name](**tool_input)
                        tool_result = json.dumps(raw)
                    except Exception as exc:
                        tool_result = "Error: %s" % exc

                tool_calls_made.append(
                    ToolCall(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_result=tool_result,
                    )
                )
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result,
                })

            current_messages.append({
                "role": "user",
                "content": tool_results_content,
            })

        # max_iterations reached
        return ToolUseResult(
            final_answer="",
            tool_calls=tool_calls_made,
            iterations=iterations,
            stop_reason="max_iterations",
        )

    async def _generate_with_tools_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executors: Dict[str, Callable],
        system: Optional[str],
        max_iterations: int,
    ) -> ToolUseResult:
        """OpenAI agentic loop: call → tool_calls → call → … → stop."""
        from openai import RateLimitError as OpenAIRateLimitError
        from openai import APIStatusError as OpenAIAPIStatusError

        client = AsyncOpenAI(
            api_key=self._api_key or "not-set",
            base_url=self._base_url,
        )

        # Convert Anthropic tool schema (input_schema) to OpenAI format (parameters)
        openai_tools = []
        for t in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            })

        current_messages: List[Dict[str, Any]] = []
        if system is not None:
            current_messages.append({"role": "system", "content": system})
        current_messages.extend(messages)

        tool_calls_made: List[ToolCall] = []
        iterations = 0
        last_error: Optional[Exception] = None

        while iterations < max_iterations:
            for attempt in range(MAX_RETRIES):
                try:
                    kwargs: Dict[str, Any] = {
                        "model": self._model_id,
                        "max_completion_tokens": self._max_tokens,
                        "messages": current_messages,
                    }
                    if openai_tools:
                        kwargs["tools"] = openai_tools
                        kwargs["reasoning_effort"] = "none"
                    response = await client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
                    last_error = None
                    break
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
            else:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("LLM API call failed after retries")

            iterations += 1
            message = response.choices[0].message

            if not message.tool_calls:
                # No tool calls — return final answer
                return ToolUseResult(
                    final_answer=message.content or "",
                    tool_calls=tool_calls_made,
                    iterations=iterations,
                    stop_reason="end_turn",
                )

            # Append assistant turn with tool_calls
            current_messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            # Execute each tool
            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, ValueError):
                    tool_input = {}

                if tool_name not in tool_executors:
                    tool_result = "Error: unknown tool '%s'" % tool_name
                else:
                    try:
                        raw = await tool_executors[tool_name](**tool_input)
                        tool_result = json.dumps(raw)
                    except Exception as exc:
                        tool_result = "Error: %s" % exc

                tool_calls_made.append(
                    ToolCall(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_result=tool_result,
                    )
                )
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

        return ToolUseResult(
            final_answer="",
            tool_calls=tool_calls_made,
            iterations=iterations,
            stop_reason="max_iterations",
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
                    max_completion_tokens=self._max_tokens,
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
