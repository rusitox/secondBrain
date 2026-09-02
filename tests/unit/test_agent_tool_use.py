"""Unit tests for LLMClient.generate_with_tools() agentic loop."""
import json
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.claude_client import LLMClient, ToolUseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.model_dump.return_value = {"type": "text", "text": text}
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_tool_use_response(name: str, tool_id: str, input_dict: Dict[str, Any]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = tool_id
    block.input = input_dict
    block.model_dump.return_value = {"type": "tool_use", "name": name, "id": tool_id, "input": input_dict}
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_client() -> LLMClient:
    return LLMClient(api_key="test-key", model="anthropic/claude-haiku-4-5-20251001")


BASE_MESSAGES = [{"role": "user", "content": "Hello"}]
BASE_TOOLS: list = []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateWithToolsNoToolUse:
    @pytest.mark.asyncio
    async def test_no_tool_use_returns_immediately(self) -> None:
        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                return_value=_make_text_response("Direct answer")
            )
            client = _make_client()
            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={},
            )

        assert result.final_answer == "Direct answer"
        assert result.stop_reason == "end_turn"
        assert result.iterations == 1
        assert result.tool_calls == []


class TestGenerateWithToolsSingleRound:
    @pytest.mark.asyncio
    async def test_single_tool_use_then_final(self) -> None:
        executor = AsyncMock(return_value=[{"content": "doc"}])

        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                side_effect=[
                    _make_tool_use_response("search_memory", "tu_1", {"query": "test"}),
                    _make_text_response("Here is the answer."),
                ]
            )
            client = _make_client()
            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={"search_memory": executor},
            )

        assert result.final_answer == "Here is the answer."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "search_memory"
        assert result.tool_calls[0].tool_input == {"query": "test"}
        assert json.loads(result.tool_calls[0].tool_result) == [{"content": "doc"}]
        assert result.iterations == 2
        executor.assert_called_once_with(query="test")


class TestGenerateWithToolsErrorPaths:
    @pytest.mark.asyncio
    async def test_unknown_tool_continues_loop(self) -> None:
        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                side_effect=[
                    _make_tool_use_response("nonexistent", "tu_2", {}),
                    _make_text_response("Recovered."),
                ]
            )
            client = _make_client()
            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={},
            )

        assert result.tool_calls[0].tool_result == "Error: unknown tool 'nonexistent'"
        assert result.final_answer == "Recovered."

    @pytest.mark.asyncio
    async def test_tool_executor_exception_continues_loop(self) -> None:
        failing_executor = AsyncMock(side_effect=RuntimeError("DB error"))

        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                side_effect=[
                    _make_tool_use_response("my_tool", "tu_3", {"x": 1}),
                    _make_text_response("Final despite error."),
                ]
            )
            client = _make_client()
            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={"my_tool": failing_executor},
            )

        assert result.tool_calls[0].tool_result == "Error: DB error"
        assert result.final_answer == "Final despite error."


class TestGenerateWithToolsMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self) -> None:
        executor = AsyncMock(return_value={"ok": True})

        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            # Always returns tool_use, never a final text
            mock_instance.messages.create = AsyncMock(
                return_value=_make_tool_use_response("loop_tool", "tu_x", {})
            )
            client = _make_client()
            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={"loop_tool": executor},
                max_iterations=2,
            )

        assert result.stop_reason == "max_iterations"
        assert result.iterations == 2


class TestGenerateWithToolsProvider:
    @pytest.mark.asyncio
    async def test_openai_provider_uses_openai_loop(self) -> None:
        """OpenAI provider routes to the OpenAI agentic loop (no error)."""
        client = LLMClient(api_key="test-key", model="openai/gpt-4o")
        with patch("app.services.llm.claude_client.AsyncOpenAI") as mock_openai_cls:
            mock_oai = MagicMock()
            mock_openai_cls.return_value = mock_oai

            msg = MagicMock()
            msg.tool_calls = None
            msg.content = "I am GPT."
            mock_choice = MagicMock()
            mock_choice.message = msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_oai.chat.completions.create = AsyncMock(return_value=mock_resp)

            result = await client.generate_with_tools(
                messages=BASE_MESSAGES,
                tools=BASE_TOOLS,
                tool_executors={},
            )

        assert result.final_answer == "I am GPT."
        assert result.stop_reason == "end_turn"


class TestGenerateWithToolsMessageAccumulation:
    @pytest.mark.asyncio
    async def test_messages_accumulate_per_iteration(self) -> None:
        executor = AsyncMock(return_value={"data": "result"})

        with patch("app.services.llm.claude_client.AsyncAnthropic") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.messages.create = AsyncMock(
                side_effect=[
                    _make_tool_use_response("my_tool", "tu_acc", {"k": "v"}),
                    _make_text_response("Done."),
                ]
            )
            client = _make_client()
            await client.generate_with_tools(
                messages=list(BASE_MESSAGES),
                tools=BASE_TOOLS,
                tool_executors={"my_tool": executor},
            )

        # Second call should receive original message + assistant turn + tool_result turn
        second_call_messages = mock_instance.messages.create.call_args_list[1].kwargs["messages"]
        assert len(second_call_messages) == 3
        assert second_call_messages[0]["role"] == "user"
        assert second_call_messages[1]["role"] == "assistant"
        assert second_call_messages[2]["role"] == "user"
        # The third message should be tool_result content
        assert second_call_messages[2]["content"][0]["type"] == "tool_result"
