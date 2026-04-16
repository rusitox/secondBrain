"""Query API endpoint for RAG-based question answering.

POST /query — answer a question using the user's knowledge base.
"""
import uuid
import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from anthropic import APIError as AnthropicAPIError

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.query import QueryRequest, QueryResponse, DocumentSource
from app.core.config import get_settings
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import ClaudeClient
from app.services.llm.prompts import RAG_SYSTEM_PROMPT, format_rag_prompt
from app.services.retrieval.filters import SearchFilters
from app.services.retrieval.search import semantic_search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@lru_cache(maxsize=1)
def _get_embedder() -> Embedder:
    settings = get_settings()
    return Embedder(api_key=settings.openai_api_key)


@lru_cache(maxsize=1)
def _get_claude_client() -> ClaudeClient:
    settings = get_settings()
    if not settings.claude_api_key:
        raise ValueError("CLAUDE_API_KEY is required for /query endpoint")
    return ClaudeClient(api_key=settings.claude_api_key)


@router.post("", response_model=QueryResponse)
async def query(
    data: QueryRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a question using RAG over the user's knowledge base."""
    # Build filters
    filters = SearchFilters(
        date_from=data.date_from,
        date_to=data.date_to,
        source=data.source,
        sources=data.sources or [],
        author=data.author,
    )

    # Step 1: Semantic search (embed query + pgvector)
    embedder = _get_embedder()
    try:
        results = await semantic_search(
            db=db,
            embedder=embedder,
            user_id=current_user_id,
            query=data.question,
            top_k=data.top_k,
            threshold=data.threshold,
            filters=filters,
        )
    except (RuntimeError, ValueError) as e:
        logger.error("Search/embedding error during query: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search service temporarily unavailable",
        )

    # Step 2: Build sources for response and context
    sources = [
        DocumentSource(
            document_id=str(r.document_id),
            content=r.content,
            source=r.source,
            source_id=r.source_id,
            metadata=r.metadata,
            similarity=r.similarity,
        )
        for r in results
    ]

    # Step 3: Generate answer via Claude
    source_dicts = [s.model_dump() for s in sources]
    user_message = format_rag_prompt(data.question, source_dicts)

    claude = _get_claude_client()
    try:
        answer = await claude.generate(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_message=user_message,
        )
    except (AnthropicAPIError, RuntimeError) as e:
        logger.error("Claude API error during query: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate answer from LLM",
        )

    return QueryResponse(
        answer=answer,
        sources=sources,
        query=data.question,
    )
