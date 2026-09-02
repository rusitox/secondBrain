"""SaveLearningTool — persist a learning or insight to long-term memory."""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.services.ingestion.embedder import Embedder

logger = logging.getLogger(__name__)

MEMORY_DEDUP_THRESHOLD = 0.92  # cosine similarity above which memory is a duplicate


class SaveLearningTool:
    """Persists learnings/insights to long-term memory with deduplication."""

    name: str = "save_learning"

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        content: str,
        entities: Optional[List[Dict[str, str]]] = None,
        importance: int = 3,
        source_type: str = "conversation",
        source_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save a learning. Returns {saved: bool, memory_id: str}."""
        embedding = await self._embedder.embed_single(content)

        # Deduplication check: find the nearest existing memory for this user.
        stmt = (
            select(Memory, Memory.embedding.cosine_distance(embedding).label("distance"))
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
            .order_by(Memory.embedding.cosine_distance(embedding))
            .limit(1)
        )
        row = (await db.execute(stmt)).first()
        if row is not None:
            mem, distance = row
            if float(distance) <= (1.0 - MEMORY_DEDUP_THRESHOLD):
                logger.info(
                    "SaveLearning: near-duplicate skipped (distance=%.3f)", distance
                )
                return {
                    "saved": False,
                    "memory_id": str(mem.id),
                    "reason": "duplicate",
                }

        memory = Memory(
            user_id=user_id,
            content=content,
            entities=entities or [],
            importance=importance,
            source_type=source_type,
            source_ref=source_ref,
            embedding=embedding,
        )
        db.add(memory)
        await db.flush()
        return {"saved": True, "memory_id": str(memory.id)}
