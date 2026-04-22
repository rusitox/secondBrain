"""Agent API endpoint for agentic, multi-tool queries.

POST /agent/query — agentic query using memory, tasks, calendar, and style tools.
"""
import uuid
import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from anthropic import APIError as AnthropicAPIError
from openai import APIError as OpenAIAPIError

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.briefing import AgentQueryRequest, AgentQueryResponse
from app.core.config import get_settings
from app.services.agent.agent import AgentOrchestrator
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
    )
