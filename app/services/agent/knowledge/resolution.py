"""Identity resolution and read-only lookup — rung 1 of the resolution ladder.

Deliberately simple within one source: exact/case-insensitive name-or-alias
matching, scoped to one user and entity type — this is what stops a domain
agent from creating a second "Juan" entity every time it re-mentions someone
it already knows about. It also means a same-source, same-name duplicate can
no longer occur, which is why Phase 4's reconciliation only ever has to deal
with genuine cross-source ambiguity (different surface name, same real
person) — never the trivial exact-match case, which never reaches it.

find_or_create_entity optionally embeds a newly-created entity's name (via
the same Embedder used for document ingestion) so Phase 4 can find
candidate cross-source duplicates by cosine similarity — see
app/services/agent/knowledge/reconciliation.py and
app/services/agent/knowledge/store.py:find_similar_entities.
"""
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityType
from app.models.entity_claim import ClaimStatus
from app.services.agent.knowledge import store


async def find_or_create_entity(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: EntityType,
    name: str,
    aliases: Optional[List[str]] = None,
    attributes: Optional[Dict[str, Any]] = None,
    embedder: Optional[Any] = None,
) -> Tuple[Entity, bool]:
    """Return (entity, created). Matches by exact case-insensitive name/alias
    within the same user + entity_type before creating a new one.

    When creating a new entity and an embedder is given, embeds
    `canonical_name` so Phase 4's reconciliation can find it by similarity —
    skipped entirely (no API call) when embedder is None, e.g. in tests.
    """
    normalized = name.strip().lower()
    candidates = await store.list_entities(db, user_id, entity_type=entity_type)

    for candidate in candidates:
        existing_names = [candidate.canonical_name, *candidate.aliases]
        if any(n.strip().lower() == normalized for n in existing_names):
            existing_lower = {n.strip().lower() for n in existing_names}
            new_aliases = [
                a for a in (aliases or []) if a.strip().lower() not in existing_lower
            ]
            if new_aliases:
                candidate.aliases = [*candidate.aliases, *new_aliases]
                await db.flush()
            return candidate, False

    embedding = None
    if embedder is not None:
        embedding = await embedder.embed_single(name)

    entity = await store.create_entity(
        db, user_id, entity_type, name, aliases=aliases, attributes=attributes,
        embedding=embedding,
    )
    return entity, True


async def consult_knowledge_base(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    entity_type: Optional[EntityType] = None,
) -> List[Dict[str, Any]]:
    """Search existing entities by name/alias before treating something as
    unknown — the first rung of the resolution ladder. Returns each match
    with its active claims so the caller can judge whether it already
    answers the question at hand."""
    entities = await store.list_entities(db, user_id, entity_type=entity_type)
    q = query.strip().lower()
    if not q:
        return []

    results: List[Dict[str, Any]] = []
    for entity in entities:
        names = [entity.canonical_name, *entity.aliases]
        if not any(q in n.lower() or n.lower() in q for n in names):
            continue
        claims = await store.list_claims(db, user_id, entity.id, status=ClaimStatus.ACTIVE)
        results.append({
            "entity_id": str(entity.id),
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "confidence": entity.confidence,
            "claims": [
                {"source": c.source, "claim_text": c.claim_text, "confidence": c.confidence}
                for c in claims
            ],
        })
    return results
