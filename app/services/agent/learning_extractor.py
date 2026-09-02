"""LearningExtractor — extract distilled learnings from ingested documents.

Runs after a batch of new documents is ingested (when enabled).
Uses the LLM to identify key facts worth remembering long-term.
"""
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.memory import Memory
from app.services.agent.tools.save_learning import SaveLearningTool
from app.services.ingestion.embedder import Embedder
from app.services.llm.claude_client import LLMClient

logger = logging.getLogger(__name__)

EXTRACTION_BATCH_SIZE = 10
MAX_EXTRACTIONS_PER_BATCH = 20

EXTRACTION_SYSTEM_PROMPT = (
    "You are a fact extraction assistant. Output only valid JSON."
)

EXTRACTION_INSTRUCTIONS = """\
Analyze the documents below and extract key facts worth remembering for future conversations.

Focus on:
- Client preferences, working styles, and constraints
- Project deadlines, milestones, and key decisions
- People's roles and relationships
- Commitments made by anyone
- Technical or organizational constraints

Output a JSON array (maximum 5 items). Each item must have:
- "content": the fact as a clear, standalone sentence
- "entities": list of {"name": ..., "type": "person"|"company"|"project"|"product"}
- "importance": integer 1-5 (1=trivia, 3=useful, 5=critical)

Output ONLY the JSON array, nothing else.
"""


class LearningExtractor:
    """Extracts distilled learnings from newly ingested content."""

    def __init__(self, llm_client: LLMClient, embedder: Embedder) -> None:
        self._llm = llm_client
        self._embedder = embedder
        self._save_tool = SaveLearningTool(embedder)

    async def extract_from_documents(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        documents: List[Document],
    ) -> List[Memory]:
        """Extract and persist learnings from a batch of documents.

        Returns list of Memory objects that were saved.
        """
        if not documents:
            return []

        saved: List[Memory] = []
        for i in range(0, len(documents), EXTRACTION_BATCH_SIZE):
            if len(saved) >= MAX_EXTRACTIONS_PER_BATCH:
                break
            batch = documents[i : i + EXTRACTION_BATCH_SIZE]
            batch_saved = await self._extract_batch(db, user_id, batch)
            saved.extend(batch_saved)

        logger.info(
            "LearningExtractor: extracted %d learnings from %d documents (user=%s)",
            len(saved),
            len(documents),
            user_id,
        )
        return saved

    async def _extract_batch(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        documents: List[Document],
    ) -> List[Memory]:
        """Extract learnings from a single batch."""
        doc_texts: List[str] = []
        for doc in documents:
            meta: Dict[str, Any] = doc.metadata_ or {}
            author = meta.get("author", "Unknown")
            source = doc.source
            doc_texts.append(f"[{source}] From {author}: {doc.content[:500]}")

        user_message = (
            EXTRACTION_INSTRUCTIONS
            + "\n\n<documents>\n"
            + "\n\n".join(doc_texts)
            + "\n</documents>"
        )

        try:
            raw = await self._llm.generate(
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.1,
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("LearningExtractor: LLM call failed: %s", e)
            return []

        try:
            facts = json.loads(raw.strip())
            if not isinstance(facts, list):
                logger.warning("LearningExtractor: unexpected response format")
                return []
        except json.JSONDecodeError as e:
            logger.warning("LearningExtractor: failed to parse JSON: %s", e)
            return []

        saved_memories: List[Memory] = []
        for fact in facts:
            if not isinstance(fact, dict) or not fact.get("content"):
                continue
            try:
                result = await self._save_tool.run(
                    db=db,
                    user_id=user_id,
                    content=fact["content"],
                    entities=fact.get("entities", []),
                    importance=fact.get("importance", 3),
                    source_type="ingestion",
                )
                if result.get("saved"):
                    mem_id = uuid.UUID(result["memory_id"])
                    stmt = select(Memory).where(Memory.id == mem_id)
                    mem = (await db.execute(stmt)).scalar_one_or_none()
                    if mem:
                        saved_memories.append(mem)
            except (RuntimeError, ValueError, KeyError) as e:
                logger.warning("LearningExtractor: failed to save fact: %s", e)

        return saved_memories
