"""Semantic search over documents using pgvector cosine similarity.

Embeds the query text, runs a cosine-distance search against
the documents table, and applies optional metadata filters.
"""
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.ingestion.embedder import Embedder
from app.services.retrieval.filters import SearchFilters

logger = logging.getLogger(__name__)

# Default similarity threshold (cosine distance: lower = more similar)
# Cosine similarity >= 0.5  <==>  cosine distance <= 0.5
DEFAULT_SIMILARITY_THRESHOLD = 0.5
DEFAULT_TOP_K = 10


@dataclass
class SearchResult:
    """A single search result with score and document data."""

    document_id: uuid.UUID
    content: str
    source: str
    source_id: str
    metadata: Dict[str, Any]
    similarity: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": str(self.document_id),
            "content": self.content,
            "source": self.source,
            "source_id": self.source_id,
            "metadata": self.metadata,
            "similarity": self.similarity,
        }


async def semantic_search(
    db: AsyncSession,
    embedder: Embedder,
    user_id: uuid.UUID,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    filters: Optional[SearchFilters] = None,
) -> List[SearchResult]:
    """Run semantic search for a user's documents.

    1. Embeds the query text via the embedder.
    2. Queries pgvector for nearest neighbors (cosine distance).
    3. Applies metadata filters (date range, source, author).
    4. Returns results sorted by similarity (highest first).
    """
    # Step 1: Embed the query
    query_embedding = await embedder.embed_single(query)

    # Step 2: Build the base query with cosine distance
    # pgvector cosine distance operator: <=>
    # similarity = 1 - cosine_distance
    cosine_distance = Document.embedding.cosine_distance(query_embedding)

    conditions = [Document.user_id == user_id]

    # Step 3: Apply filters
    if filters:
        if filters.source:
            conditions.append(Document.source == filters.source)
        if filters.sources:
            conditions.append(Document.source.in_(filters.sources))
        if filters.author:
            conditions.append(
                Document.metadata_["author"].astext == filters.author
            )
        if filters.date_from:
            conditions.append(
                Document.metadata_["timestamp"].astext >= filters.date_from.isoformat()
            )
        if filters.date_to:
            conditions.append(
                Document.metadata_["timestamp"].astext <= filters.date_to.isoformat()
            )

    stmt = (
        select(
            Document,
            cosine_distance.label("distance"),
        )
        .where(and_(*conditions))
        .order_by(cosine_distance.asc())
        .limit(top_k)
    )

    result = await db.execute(stmt)
    rows = result.all()  # type: ignore[assignment]

    # Step 4: Filter by threshold and build results
    search_results: List[SearchResult] = []
    for doc, distance in rows:
        similarity = 1.0 - distance
        if similarity < threshold:
            continue
        search_results.append(
            SearchResult(
                document_id=doc.id,
                content=doc.content,
                source=doc.source,
                source_id=doc.source_id,
                metadata=doc.metadata_ or {},
                similarity=round(similarity, 4),
            )
        )

    logger.info(
        "Semantic search for user=%s returned %d results (query=%r, top_k=%d, threshold=%.2f)",
        user_id, len(search_results), query[:50], top_k, threshold,
    )
    return search_results
