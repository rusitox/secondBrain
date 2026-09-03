"""Agent API endpoint for agentic, multi-tool queries.

POST /agent/query  — agentic query using memory, tasks, calendar, and style tools.
POST /agent/stream — same query but streamed via Server-Sent Events.
"""
import asyncio
import json as json_module
import uuid
import logging
from functools import lru_cache
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from anthropic import APIError as AnthropicAPIError
from openai import APIError as OpenAIAPIError

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.briefing import AgentQueryRequest, AgentQueryResponse, AgentStreamRequest
from app.core.config import get_settings
from app.services.agent.agent import AgentOrchestrator, AGENT_SYSTEM_PROMPT
from app.services.agent.tool_definitions import AGENT_TOOLS
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@lru_cache(maxsize=1)
def _get_agent() -> AgentOrchestrator:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is required for /agent/query endpoint")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for /agent/query endpoint")
    claude_client = ClaudeClient(api_key=settings.llm_api_key, model=settings.llm_model)
    embedder = Embedder(api_key=settings.openai_api_key)
    return AgentOrchestrator(claude_client=claude_client, embedder=embedder)


@router.post("/query", response_model=AgentQueryResponse)
async def agent_query(
    data: AgentQueryRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AgentQueryResponse:
    """Answer a question using the agentic multi-tool pipeline."""
    agent = _get_agent()
    try:
        result = await agent.query(
            db=db,
            user_id=current_user_id,
            question=data.question,
            session_id=data.session_id,
        )
    except (AnthropicAPIError, OpenAIAPIError, RuntimeError) as e:
        logger.error("Agent query error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to process agent query",
        )

    return AgentQueryResponse(
        answer=result["answer"],
        tools_used=result["tools_used"],
        sources=result.get("sources", []),
        query=data.question,
        session_id=result.get("session_id", ""),
        iterations=result.get("iterations", 0),
    )


@router.post("/stream")
async def agent_stream(
    data: AgentStreamRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> "EventSourceResponse":  # type: ignore[name-defined]
    """Stream an agent query response using Server-Sent Events.

    Events emitted:
      tool_call   — when a tool is being called   (data: {"tool": str, "status": "calling"})
      tool_result — when a tool call completes     (data: {"tool": str, "status": "done"})
      token       — a text token from final answer (data: {"text": str})
      done        — final event with metadata       (data: {"session_id": str, "iterations": int, ...})
      error       — on failure                      (data: {"detail": str})
    """
    from sse_starlette.sse import EventSourceResponse

    async def event_generator() -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue()

        async def on_tool_call(tool_name: str) -> None:
            await queue.put({"event": "tool_call", "data": json_module.dumps({"tool": tool_name, "status": "calling"})})

        async def on_tool_result(tool_name: str) -> None:
            await queue.put({"event": "tool_result", "data": json_module.dumps({"tool": tool_name, "status": "done"})})

        async def on_token(text: str) -> None:
            await queue.put({"event": "token", "data": json_module.dumps({"text": text})})

        SENTINEL = object()

        async def run_query() -> None:
            try:
                agent = _get_agent()
                resolved_session_id, history = await agent._resolve_session(
                    db, current_user_id, data.session_id
                )

                messages = history + [{"role": "user", "content": data.question}]

                tool_executors = {
                    "search_memory": agent._make_search_memory(db, current_user_id),
                    "list_tasks": agent._make_list_tasks(db, current_user_id),
                    "get_calendar": agent._make_get_calendar(db, current_user_id),
                    "get_user_style": agent._make_get_user_style(db, current_user_id),
                    "save_learning": agent._make_save_learning(db, current_user_id),
                    "search_learnings": agent._make_search_learnings(db, current_user_id),
                }

                # Wrap executors to emit tool_call / tool_result events
                wrapped_executors = {}
                for name, executor in tool_executors.items():
                    async def _wrap(_name: str = name, _executor: object = executor, **kwargs: object) -> object:
                        await on_tool_call(_name)
                        result = await _executor(**kwargs)  # type: ignore[operator]
                        await on_tool_result(_name)
                        return result
                    wrapped_executors[name] = _wrap

                result = await agent._llm.generate_with_tools(
                    messages=messages,
                    tools=AGENT_TOOLS,
                    tool_executors=wrapped_executors,
                    system=AGENT_SYSTEM_PROMPT,
                    stream_callback=on_token,
                )

                await agent._persist_turns(
                    db=db,
                    user_id=current_user_id,
                    sid=resolved_session_id,
                    question=data.question,
                    answer=result.final_answer,
                    tool_calls=result.tool_calls,
                )

                await queue.put({
                    "event": "done",
                    "data": json_module.dumps({
                        "session_id": resolved_session_id,
                        "iterations": result.iterations,
                        "tools_used": [tc.tool_name for tc in result.tool_calls],
                    }),
                })
            except asyncio.CancelledError:
                raise
            except (AnthropicAPIError, OpenAIAPIError, RuntimeError) as e:
                logger.error("Agent stream error: %s", e)
                await queue.put({
                    "event": "error",
                    "data": json_module.dumps({"detail": "Agent query failed. Please try again."}),
                })
            finally:
                await queue.put(SENTINEL)

        task = asyncio.create_task(run_query())

        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        await task  # propagate any unhandled exceptions

    return EventSourceResponse(event_generator())
