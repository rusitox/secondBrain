"""SearchLearningsTool — semantic search over distilled memory entries."""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.services.ingestion.embedder import Embedder

logger = logging.getLogger(__name__)


class SearchLearningsTool:
    """Searches the user's long-term learnings via semantic similarity."""

    name: str = "search_learnings"

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
        entity_name: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search memories and return ranked results."""
        embedding = await self._embedder.embed_single(query)

        stmt = (
            select(Memory, Memory.embedding.cosine_distance(embedding).label("distance"))
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
        )

        if entity_name is not None:
            stmt = stmt.where(
                Memory.entities.contains([{"name": entity_name}])
            )

        stmt = stmt.order_by(Memory.embedding.cosine_distance(embedding)).limit(top_k)
        rows = (await db.execute(stmt)).all()

        return [
            {
                "content": mem.content,
                "entities": mem.entities,
                "importance": mem.importance,
                "source_type": mem.source_type,
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
                "similarity": round(1.0 - float(distance), 4),
                "memory_id": str(mem.id),
            }
            for mem, distance in rows
        ]
