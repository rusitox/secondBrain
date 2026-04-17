"""Memory retriever tool — semantic search over user's knowledge base."""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ingestion.embedder import Embedder
from app.services.retrieval.filters import SearchFilters
from app.services.retrieval.search import SearchResult, semantic_search

logger = logging.getLogger(__name__)


class MemoryRetrieverTool:
    """Searches the user's knowledge base via semantic search."""

    name: str = "memory_retriever"
    description: str = (
        "Search the user's personal knowledge base (emails, messages, meeting notes). "
        "Use this to find information the user has received or discussed."
    )

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
        source: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the knowledge base and return results."""
        filters = SearchFilters(source=source) if source else None
        results = await semantic_search(
            db=db,
            embedder=self._embedder,
            user_id=user_id,
            query=query,
            top_k=top_k,
            filters=filters,
        )
        return [r.to_dict() for r in results]
