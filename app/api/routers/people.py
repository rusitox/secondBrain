"""Relationship-intelligence panel — who the user interacts with, grouped by
what the domain agents have learned about their role, how they relate to the
user, their communication style, how to reach agreements with them, and
what decisions they can make.

Read-only, zero LLM calls, same shape as app/api/routers/systems.py: compose
existing knowledge-graph data (app/services/agent/knowledge/store.py), never
re-derive it. GET /people/today-equivalent doesn't apply here — unlike the
backlog, this isn't date-scoped, so there's no cache-vs-poll question: a
plain fetch-on-open is enough.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.people import ClaimOut, PeopleListResponse, PersonProfile, PersonSummary, RelatedEntityOut
from app.models.entity import EntityType
from app.services.agent.knowledge import store as knowledge_store

router = APIRouter(prefix="/people", tags=["people"])

# Confirmed live against a real account: 1937 PERSON entities exist (the
# knowledge graph's entity extraction isn't precise — e.g. a bare email
# address like "info@cesams.com" can land as its own PERSON entity — a
# pre-existing data-quality gap in the graph itself, not something this
# endpoint can fix). Profiling every one of them (claims + links) to list
# just their names/roles measured at ~2.5ms/entity, projecting to ~5s for
# the full set — fine today, but it only grows, and a 1937-row list isn't
# a usable "who do I interact with" panel either. Capped to the top N by
# confidence (the entities the graph is most sure are real/corroborated),
# profiled only after the cap — same shape as daily_planning.py's
# max_per_kind and the pending-questions cap found in that same bug hunt.
PEOPLE_LIST_LIMIT = 50


def _role_from_profile(profile: dict) -> Optional[str]:
    role_claims = profile["claim_groups"].get("role")
    return role_claims[0].claim_text if role_claims else None


@router.get("", response_model=PeopleListResponse)
async def list_people(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entities = await knowledge_store.list_entities(db, current_user_id, entity_type=EntityType.PERSON)
    entities.sort(key=lambda e: e.confidence, reverse=True)
    entities = entities[:PEOPLE_LIST_LIMIT]

    summaries: List[PersonSummary] = []
    for entity in entities:
        profile = await knowledge_store.get_entity_profile(db, current_user_id, entity.id)
        summaries.append(PersonSummary(
            entity_id=str(entity.id),
            canonical_name=entity.canonical_name,
            confidence=entity.confidence,
            role=_role_from_profile(profile) if profile else None,
        ))

    return {"people": summaries}


@router.get("/{entity_id}", response_model=PersonProfile)
async def get_person(
    entity_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = await knowledge_store.get_entity_profile(db, current_user_id, entity_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")

    entity = profile["entity"]
    related = await knowledge_store.resolve_related_entities(
        db, current_user_id, entity_id, profile["links"],
    )
    related_entities = [RelatedEntityOut(**r) for r in related]

    return {
        "entity_id": str(entity.id),
        "canonical_name": entity.canonical_name,
        "confidence": entity.confidence,
        "attributes": profile["attributes"],
        "claims_by_type": {
            claim_type: [
                ClaimOut(claim_text=c.claim_text, source=c.source, confidence=c.confidence)
                for c in claims
            ]
            for claim_type, claims in profile["claim_groups"].items()
        },
        "related_entities": related_entities,
    }
