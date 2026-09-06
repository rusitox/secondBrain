"""CRUD helpers for the multi-agent knowledge schema.

Phase 0 of specs/plan-multi-agent-knowledge.md: pure data access, no LLM or
agent logic. Domain agents (Phase 1+) call these functions as the building
blocks for their tools; this module has no opinion on when/why to call them.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select
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


async def find_similar_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity: Entity,
    max_distance: float = 0.15,
    limit: int = 5,
) -> List[Entity]:
    """Entities of the same type most similar to `entity` by embedding cosine
    distance (excluding itself) — Phase 4's candidate-duplicate detection.

    max_distance is 1 - cosine_similarity, so lower means more similar; 0.15
    corresponds to similarity >= 0.85. Requires pgvector (Postgres) — same
    cosine_distance() pattern as SaveLearningTool's dedup check. Returns []
    when the entity has no embedding (e.g. created without an embedder).
    """
    if entity.embedding is None:
        return []
    stmt = (
        select(Entity)
        .where(
            Entity.user_id == user_id,
            Entity.entity_type == entity.entity_type,
            Entity.id != entity.id,
            Entity.embedding.isnot(None),
            Entity.embedding.cosine_distance(entity.embedding) <= max_distance,
        )
        .order_by(Entity.embedding.cosine_distance(entity.embedding))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


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


async def get_question(
    db: AsyncSession, user_id: uuid.UUID, question_id: uuid.UUID
) -> Optional[PendingQuestion]:
    """Scoped by user_id — a question_id belonging to another user must never resolve."""
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
    question = await get_question(db, user_id, question_id)
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
    question = await get_question(db, user_id, question_id)
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


# ---------------------------------------------------------------------------
# Observability (Phase 7) — is the knowledge base actually getting more solid?
# ---------------------------------------------------------------------------

CONFIDENCE_BUCKETS = ("low", "medium", "high")


async def get_knowledge_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    merged_window_hours: int = 24,
) -> Dict[str, Any]:
    """Aggregate snapshot of the shared knowledge base's current solidity.

    Every count is computed in SQL (GROUP BY / COUNT), never by loading every
    Entity/EntityClaim/PendingQuestion row into Python — this is meant to run
    cheaply on every dashboard/status check, not just once in a while.
    """
    confidence_bucket = case(
        (Entity.confidence < 0.4, "low"),
        (Entity.confidence < 0.7, "medium"),
        else_="high",
    )
    confidence_rows = (
        await db.execute(
            select(confidence_bucket, func.count())
            .where(Entity.user_id == user_id)
            .group_by(confidence_bucket)
        )
    ).all()
    entities_by_confidence = {bucket: 0 for bucket in CONFIDENCE_BUCKETS}
    for bucket, count in confidence_rows:
        entities_by_confidence[bucket] = count

    type_rows = (
        await db.execute(
            select(Entity.entity_type, func.count())
            .where(Entity.user_id == user_id)
            .group_by(Entity.entity_type)
        )
    ).all()
    entities_by_type = {entity_type.value: count for entity_type, count in type_rows}

    source_rows = (
        await db.execute(
            select(EntityClaim.source, func.count())
            .where(EntityClaim.user_id == user_id)
            .group_by(EntityClaim.source)
        )
    ).all()
    claims_by_source = {source: count for source, count in source_rows}

    status_rows = (
        await db.execute(
            select(EntityClaim.status, func.count())
            .where(EntityClaim.user_id == user_id)
            .group_by(EntityClaim.status)
        )
    ).all()
    claims_by_status = {claim_status.value: count for claim_status, count in status_rows}

    target_rows = (
        await db.execute(
            select(PendingQuestion.target, func.count())
            .where(
                PendingQuestion.user_id == user_id,
                PendingQuestion.status == QuestionStatus.OPEN,
            )
            .group_by(PendingQuestion.target)
        )
    ).all()
    pending_questions_by_target = {target.value: count for target, count in target_rows}

    since = datetime.now(timezone.utc) - timedelta(hours=merged_window_hours)
    entities_merged_recent = (
        await db.execute(
            select(func.count())
            .select_from(EntityLink)
            .where(
                EntityLink.user_id == user_id,
                EntityLink.relation_type == "same_as",
                EntityLink.created_at >= since,
            )
        )
    ).scalar_one()

    return {
        "total_entities": sum(entities_by_confidence.values()),
        "entities_by_confidence": entities_by_confidence,
        "entities_by_type": entities_by_type,
        "total_claims": sum(claims_by_source.values()),
        "claims_by_source": claims_by_source,
        "claims_by_status": claims_by_status,
        "pending_questions_open": sum(pending_questions_by_target.values()),
        "pending_questions_by_target": pending_questions_by_target,
        "entities_merged_recent": entities_merged_recent,
        "merged_window_hours": merged_window_hours,
    }
