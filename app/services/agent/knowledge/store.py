"""CRUD helpers for the multi-agent knowledge schema.

Phase 0 of specs/plan-multi-agent-knowledge.md: pure data access, no LLM or
agent logic. Domain agents (Phase 1+) call these functions as the building
blocks for their tools; this module has no opinion on when/why to call them.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.entity import Entity, EntityType
from app.models.entity_claim import ClaimStatus, EntityClaim
from app.models.entity_link import EntityLink, LinkResolvedBy
from app.models.pending_question import (
    PendingQuestion,
    QuestionStatus,
    QuestionTarget,
    ResolvedBy,
)
from app.models.processed_document import ProcessedDocument


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

async def create_entity(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: EntityType,
    canonical_name: str,
    aliases: Optional[List[str]] = None,
    attributes: Optional[Dict[str, Any]] = None,
    embedding: Optional[List[float]] = None,
    confidence: float = 0.5,
) -> Entity:
    entity = Entity(
        user_id=user_id,
        entity_type=entity_type,
        canonical_name=canonical_name,
        aliases=aliases or [],
        attributes=attributes or {},
        embedding=embedding,
        confidence=confidence,
    )
    db.add(entity)
    await db.flush()
    return entity


async def get_entity(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID
) -> Optional[Entity]:
    """Scoped by user_id — an entity_id belonging to another user must never resolve."""
    stmt = select(Entity).where(Entity.id == entity_id, Entity.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: Optional[EntityType] = None,
) -> List[Entity]:
    stmt = select(Entity).where(Entity.user_id == user_id)
    if entity_type is not None:
        stmt = stmt.where(Entity.entity_type == entity_type)
    return list((await db.execute(stmt)).scalars().all())


async def update_entity_confidence(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID, confidence: float
) -> Optional[Entity]:
    entity = await get_entity(db, user_id, entity_id)
    if entity is not None:
        entity.confidence = confidence
        await db.flush()
    return entity


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

async def add_claim(
    db: AsyncSession,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    source: str,
    claim_text: str,
    asserted_by_agent: str,
    source_ref: Optional[str] = None,
    claim_type: Optional[str] = None,
    confidence: float = 0.5,
    status: ClaimStatus = ClaimStatus.ACTIVE,
) -> EntityClaim:
    """Raises ValueError if entity_id doesn't exist or belongs to another user."""
    if await get_entity(db, user_id, entity_id) is None:
        raise ValueError(f"entity {entity_id} not found for this user")

    claim = EntityClaim(
        entity_id=entity_id,
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        claim_text=claim_text,
        claim_type=claim_type,
        confidence=confidence,
        status=status,
        asserted_by_agent=asserted_by_agent,
    )
    db.add(claim)
    await db.flush()
    return claim


async def list_claims(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_id: uuid.UUID,
    status: Optional[ClaimStatus] = None,
) -> List[EntityClaim]:
    stmt = select(EntityClaim).where(
        EntityClaim.entity_id == entity_id, EntityClaim.user_id == user_id
    )
    if status is not None:
        stmt = stmt.where(EntityClaim.status == status)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

async def link_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_id_a: uuid.UUID,
    entity_id_b: uuid.UUID,
    relation_type: str,
    resolved_by: LinkResolvedBy,
    confidence: float = 0.5,
) -> EntityLink:
    """Raises ValueError if either entity doesn't exist or belongs to another user."""
    if await get_entity(db, user_id, entity_id_a) is None:
        raise ValueError(f"entity {entity_id_a} not found for this user")
    if await get_entity(db, user_id, entity_id_b) is None:
        raise ValueError(f"entity {entity_id_b} not found for this user")

    link = EntityLink(
        user_id=user_id,
        entity_id_a=entity_id_a,
        entity_id_b=entity_id_b,
        relation_type=relation_type,
        confidence=confidence,
        resolved_by=resolved_by,
    )
    db.add(link)
    await db.flush()
    return link


async def list_links_for_entity(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID
) -> List[EntityLink]:
    stmt = select(EntityLink).where(
        EntityLink.user_id == user_id,
        (EntityLink.entity_id_a == entity_id) | (EntityLink.entity_id_b == entity_id),
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Pending questions — the resolution-ladder state machine
# ---------------------------------------------------------------------------

async def raise_question(
    db: AsyncSession,
    user_id: uuid.UUID,
    raised_by_agent: str,
    question_text: str,
    context: Optional[Dict[str, Any]] = None,
    target: QuestionTarget = QuestionTarget.PEER_AGENTS,
    candidate_answer: Optional[str] = None,
    candidate_confidence: Optional[float] = None,
) -> PendingQuestion:
    """Create a question at the start of the resolution ladder (default: peer agents first)."""
    question = PendingQuestion(
        user_id=user_id,
        raised_by_agent=raised_by_agent,
        question_text=question_text,
        context=context or {},
        target=target,
        candidate_answer=candidate_answer,
        candidate_confidence=candidate_confidence,
    )
    db.add(question)
    await db.flush()
    return question


async def _get_question(
    db: AsyncSession, user_id: uuid.UUID, question_id: uuid.UUID
) -> Optional[PendingQuestion]:
    stmt = select(PendingQuestion).where(
        PendingQuestion.id == question_id, PendingQuestion.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def escalate_to_human(
    db: AsyncSession,
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    candidate_answer: Optional[str] = None,
    candidate_confidence: Optional[float] = None,
) -> Optional[PendingQuestion]:
    """Flip a question's target to HUMAN — only after peer agents couldn't resolve it.

    Carries forward whatever partial answer the peer-agent step produced, if any,
    so the human validates a candidate instead of answering cold.
    """
    question = await _get_question(db, user_id, question_id)
    if question is None:
        return None
    question.target = QuestionTarget.HUMAN
    if candidate_answer is not None:
        question.candidate_answer = candidate_answer
    if candidate_confidence is not None:
        question.candidate_confidence = candidate_confidence
    await db.flush()
    return question


async def resolve_question(
    db: AsyncSession,
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    resolved_by: ResolvedBy,
    answer_text: Optional[str] = None,
    status: QuestionStatus = QuestionStatus.ANSWERED,
) -> Optional[PendingQuestion]:
    question = await _get_question(db, user_id, question_id)
    if question is None:
        return None
    question.status = status
    question.resolved_by = resolved_by
    question.answer_text = answer_text
    question.answered_at = datetime.now(timezone.utc)
    await db.flush()
    return question


async def list_open_questions(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: Optional[QuestionTarget] = None,
) -> List[PendingQuestion]:
    stmt = select(PendingQuestion).where(
        PendingQuestion.user_id == user_id,
        PendingQuestion.status == QuestionStatus.OPEN,
    )
    if target is not None:
        stmt = stmt.where(PendingQuestion.target == target)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Document processing tracking
# ---------------------------------------------------------------------------

async def get_unprocessed_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
    source: str,
    limit: int = 20,
) -> List[Document]:
    """Documents for this source a domain agent hasn't extracted yet.

    A document that yields nothing still gets marked processed (via
    mark_document_processed) so it isn't re-read on every batch forever.
    """
    processed_ids = select(ProcessedDocument.document_id).where(
        ProcessedDocument.user_id == user_id,
        ProcessedDocument.source == source,
    )
    stmt = (
        select(Document)
        .where(
            Document.user_id == user_id,
            Document.source == source,
            Document.id.notin_(processed_ids),
        )
        .order_by(Document.created_at.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def mark_document_processed(
    db: AsyncSession,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    source: str,
) -> ProcessedDocument:
    """Raises ValueError if document_id doesn't exist or belongs to another user."""
    doc_stmt = select(Document).where(Document.id == document_id, Document.user_id == user_id)
    if (await db.execute(doc_stmt)).scalar_one_or_none() is None:
        raise ValueError(f"document {document_id} not found for this user")

    record = ProcessedDocument(user_id=user_id, document_id=document_id, source=source)
    db.add(record)
    await db.flush()
    return record
