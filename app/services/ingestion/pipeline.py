"""Ingestion pipeline orchestrator.

Flow: raw text → clean → chunk → embed → upsert to DB → detect commitments.
Handles deduplication via (user_id, source, source_id) unique index.
"""
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.ingestion.cleaner import clean_text
from app.services.ingestion.chunker import chunk_text
from app.services.ingestion.embedder import Embedder

if TYPE_CHECKING:
    from app.services.commitments.detector import CommitmentDetector

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of an ingestion run."""

    documents_created: int = 0
    documents_updated: int = 0
    documents_skipped: int = 0
    chunks_total: int = 0
    commitments_detected: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "documents_created": self.documents_created,
            "documents_updated": self.documents_updated,
            "documents_skipped": self.documents_skipped,
            "chunks_total": self.chunks_total,
            "commitments_detected": self.commitments_detected,
        }


class IngestionPipeline:
    """Orchestrates the full ingestion flow."""

    def __init__(
        self,
        embedder: Embedder,
        commitment_detector: Optional["CommitmentDetector"] = None,
    ) -> None:
        self._embedder = embedder
        self._commitment_detector = commitment_detector

    async def ingest_raw(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        content: str,
        source: str,
        source_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """Ingest a single raw text document.

        Cleans, chunks, embeds, and upserts to DB.
        If chunks produce multiple documents, each gets a unique source_id suffix.
        """
        result = IngestionResult()
        metadata = metadata or {}

        # Step 1: Clean
        cleaned = clean_text(content, source)
        if not cleaned:
            logger.info("Text was empty after cleaning, skipping")
            result.documents_skipped = 1
            return result

        # Step 2: Chunk
        chunks = chunk_text(cleaned)
        if not chunks:
            logger.info("No chunks produced, skipping")
            result.documents_skipped = 1
            return result

        result.chunks_total = len(chunks)

        # Step 3: Embed all chunks in batch
        embeddings = await self._embedder.embed_texts(chunks)

        # Step 4: Upsert each chunk as a document
        doc_ids: List[uuid.UUID] = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_source_id = source_id if len(chunks) == 1 else f"{source_id}#chunk{i}"
            doc_id = await self._upsert_document(
                db=db,
                user_id=user_id,
                content=chunk,
                embedding=embedding,
                source=source,
                source_id=chunk_source_id,
                metadata=metadata,
                result=result,
            )
            if doc_id is not None:
                doc_ids.append(doc_id)

        await db.flush()

        # Step 5: Detect commitments (only on newly created documents, once per text)
        if self._commitment_detector and doc_ids:
            timestamp = metadata.get("timestamp", "")
            commitments = await self._commitment_detector.detect_and_store(
                db=db,
                user_id=user_id,
                document_id=doc_ids[0],
                text=cleaned,
                timestamp=timestamp,
            )
            result.commitments_detected += len(commitments)

        return result

    async def ingest_batch(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        items: List[Dict[str, Any]],
        source: str,
    ) -> IngestionResult:
        """Ingest multiple items from a connector.

        Each item should have: content, source_id, metadata (optional).
        """
        result = IngestionResult()

        for item in items:
            item_result = await self.ingest_raw(
                db=db,
                user_id=user_id,
                content=item["content"],
                source=source,
                source_id=item.get("source_id", ""),
                metadata=item.get("metadata"),
            )
            result.documents_created += item_result.documents_created
            result.documents_updated += item_result.documents_updated
            result.documents_skipped += item_result.documents_skipped
            result.chunks_total += item_result.chunks_total
            result.commitments_detected += item_result.commitments_detected

        return result

    async def _upsert_document(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        content: str,
        embedding: List[float],
        source: str,
        source_id: str,
        metadata: Dict[str, Any],
        result: IngestionResult,
    ) -> Optional[uuid.UUID]:
        """Insert or update a document based on (user_id, source, source_id).

        Returns the document ID for newly created documents, None for updates.
        """
        # Check for existing document
        existing = await db.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.source == source,
                Document.source_id == source_id,
            )
        )
        doc = existing.scalar_one_or_none()

        if doc is not None:
            # Update existing
            doc.content = content
            doc.embedding = embedding
            doc.metadata_ = metadata
            result.documents_updated += 1
            logger.debug("Updated document %s (source=%s, source_id=%s)", doc.id, source, source_id)
            return None
        else:
            # Create new
            doc = Document(
                id=uuid.uuid4(),
                user_id=user_id,
                content=content,
                embedding=embedding,
                source=source,
                source_id=source_id,
                metadata_=metadata,
            )
            db.add(doc)
            result.documents_created += 1
            logger.debug("Created document (source=%s, source_id=%s)", source, source_id)
            return doc.id
