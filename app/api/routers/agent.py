"""Agent API endpoint for agentic, multi-tool queries.

POST /agent/query  — agentic query using memory, tasks, calendar, and style tools.
POST /agent/stream — same query but streamed via Server-Sent Events.
"""
import asyncio
import json as json_module
import uuid
import logging
from functools import lru_cache
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from anthropic import APIError as AnthropicAPIError
from openai import APIError as OpenAIAPIError
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.briefing import AgentQueryRequest, AgentQueryResponse, AgentStreamRequest
from app.api.schemas.stream import EVENT_SCHEMAS
from app.core.config import get_settings
from app.services.agent.strands_orchestrator import StrandsOrchestrator
from app.services.ingestion.embedder import Embedder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@lru_cache(maxsize=1)
def _get_agent() -> StrandsOrchestrator:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is required for /agent/query endpoint")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for /agent/query endpoint")
    embedder = Embedder(api_key=settings.openai_api_key)
    return StrandsOrchestrator(embedder=embedder)


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
    except (AnthropicAPIError, OpenAIAPIError, RuntimeError, SQLAlchemyError) as e:
        # SQLAlchemyError added alongside the interrupt-handling DB writes
        # in _finalize_turn (create_interaction/upsert_session_state) — a
        # failure there used to escape as a raw unhandled 500 on this
        # non-streaming endpoint, unlike /agent/stream's own broadened
        # exception handling for the identical code path.
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
        stop_reason=result.get("stop_reason", "end_turn"),
        awaiting=result.get("awaiting", []),
    )


@router.post("/stream")
async def agent_stream(
    data: AgentStreamRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> "EventSourceResponse":  # type: ignore[name-defined]
    """Stream an agent query response using Server-Sent Events.

    Events emitted (see app.api.schemas.stream for the typed payload shapes):
      session     — first event, before anything else (data: {"session_id", "turn_id"})
      thinking    — a "thinking process" panel row     (data: {"id","category"?,"label"?,"status","detail"?})
      token       — a text token from the final answer (data: {"text": str})
      tool_result — a tool call's summarized result     (data: {"id","tool","ok","summary"})
      done        — final event with metadata           (data: {"session_id","turn_id","stop_reason","iterations","tools_used","awaiting"})
      error       — on failure                           (data: {"detail": str})
    """
    from sse_starlette.sse import EventSourceResponse

    async def event_generator() -> AsyncIterator[dict]:
        queue: "asyncio.Queue[Any]" = asyncio.Queue()
        SENTINEL = object()

        def emit(event: str, event_data: Dict[str, Any]) -> None:
            # Synchronous by design — see _StreamingCallbackHandler in
            # strands_orchestrator.py for why. put_nowait is safe here
            # because Strands always invokes the callback (and thus this
            # closure) from the same task that owns this queue.
            #
            # Validating through EVENT_SCHEMAS here — the one place every
            # event from both the callback handler and this router's own
            # session/done/error calls funnels through — is what makes
            # app.api.schemas.stream an actual contract rather than
            # documentation: a payload that doesn't match its schema (e.g.
            # a stop_reason outside the 3-value closed set) fails the
            # request instead of silently reaching the client malformed.
            validated = EVENT_SCHEMAS[event](**event_data).model_dump(exclude_none=True)
            queue.put_nowait({"event": event, "data": json_module.dumps(validated)})

        async def run_query() -> None:
            try:
                agent_inst = _get_agent()
                result = await agent_inst.query(
                    db=db,
                    user_id=current_user_id,
                    question=data.question,
                    session_id=data.session_id,
                    emit=emit,
                )

                emit("done", {
                    "session_id": result.get("session_id", ""),
                    "turn_id": result.get("turn_id", ""),
                    "stop_reason": result.get("stop_reason", "end_turn"),
                    "iterations": result.get("iterations", 0),
                    "tools_used": result.get("tools_used", []),
                    "awaiting": result.get("awaiting", []),
                })
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Deliberately broad, unlike the /agent/query except tuple
                # above: this runs inside an SSE generator, so anything
                # that escapes it just closes the stream with no "error"
                # event and no way for FastAPI to turn it into a normal
                # HTTP error response. That includes SQLAlchemyError from
                # _finalize_turn's interrupt-branch DB writes and whatever
                # Strands' own snapshot/interrupt internals can raise.
                logger.exception("Agent stream error: %s", e)
                emit("error", {"detail": "Agent query failed. Please try again."})
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

    return EventSourceResponse(event_generator())
