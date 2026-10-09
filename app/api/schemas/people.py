"""GET /people, GET /people/{entity_id} — the relationship-intelligence panel.

Read-only views over the same PERSON entities/claims the knowledge graph
already has (app/services/agent/knowledge) — no LLM call, no new storage.
See app/services/agent/knowledge/store.py's get_entity_profile for the
single aggregation point both this router and the get_person_profile agent
tool share.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel


class PersonSummary(BaseModel):
    entity_id: str
    canonical_name: str
    confidence: float
    role: Optional[str] = None  # newest "role"-typed claim's text, if any


class ClaimOut(BaseModel):
    claim_text: str
    source: str
    confidence: float


class RelatedEntityOut(BaseModel):
    relation_type: str
    entity_id: str
    canonical_name: Optional[str] = None


class PersonProfile(BaseModel):
    entity_id: str
    canonical_name: str
    confidence: float
    attributes: Dict[str, object]
    claims_by_type: Dict[str, List[ClaimOut]]
    related_entities: List[RelatedEntityOut]


class PeopleListResponse(BaseModel):
    people: List[PersonSummary]
