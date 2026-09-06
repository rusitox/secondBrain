"""Reconciliation engine — Phase 4 of specs/plan-multi-agent-knowledge.md.

Runs after a batch of domain agents finish extracting for a sync cycle (not
wired to the live scheduler yet — see run_reconciliation's docstring). This
is not a second negotiation mechanism: the same scoped-Swarm pattern
domain_agent._ask_peer_agents uses *proactively* (an agent has a doubt about
one entity) is used here *reactively* (a batch scan flags a candidate
cross-source duplicate pair) — one negotiation core, two triggers, per the
plan's own wording.

Deterministic pre-filter runs first and never costs an LLM call:
- Exact email match (Entity.attributes["email"]) auto-links as same_as with
  confidence 1.0.
- Exact same-name duplicates cannot occur in the first place — Phase 1's
  find_or_create_entity already prevents them within one source, and an
  exact name match across sources would already have been caught by that
  same lookup regardless of which domain agent created the entity (it
  searches all of the user's entities of that type, not just its own
  source's). So the only duplicates that ever reach this module are
  genuine cross-source ambiguity: different surface name, same real
  person — which is exactly what embedding similarity below is for.
- Everything else goes through cosine similarity (store.find_similar_entities)
  to find candidates actually worth asking about. Below the threshold,
  entities are left alone — no swarm spent guessing at unrelated entities.

Ambiguous candidates negotiate via a scoped Swarm deciding "are these the
same real-world entity?", concluded via a dedicated submit_same_as_verdict
tool. No consensus -> pending_questions(target=human) carrying whatever
partial verdict the swarm reached, never a blind question. A pair with an
already-open question is skipped rather than re-negotiated every cycle —
the same cost-threshold requirement the plan's risk section calls for.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityType
from app.models.entity_claim import ClaimStatus
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionTarget
from app.services.agent.knowledge import store

logger = logging.getLogger(__name__)

SIMILARITY_MAX_DISTANCE = 0.15  # cosine distance <= this ~ cosine similarity >= 0.85
SAME_AS_CONFIDENCE_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Deterministic pre-filter
# ---------------------------------------------------------------------------

async def _already_linked(
    db: AsyncSession, user_id: uuid.UUID, entity_a_id: uuid.UUID, entity_b_id: uuid.UUID
) -> bool:
    """True only for an existing same_as link — entity_link.py's own
    docstring anticipates other relation types (e.g. a future
    "collaborates_on"), and those must never block a legitimate same_as
    merge just because some other relationship already exists between
    the same two entities."""
    links = await store.list_links_for_entity(db, user_id, entity_a_id)
    return any(
        link.relation_type == "same_as" and {link.entity_id_a, link.entity_id_b} == {entity_a_id, entity_b_id}
        for link in links
    )


async def auto_link_by_email(db: AsyncSession, user_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Entities sharing an exact attributes['email'] are the same person —
    no negotiation needed. Returns a summary of the links created."""
    people = await store.list_entities(db, user_id, entity_type=EntityType.PERSON)
    by_email: Dict[str, List[Entity]] = {}
    for person in people:
        email = (person.attributes or {}).get("email")
        if email:
            by_email.setdefault(email.strip().lower(), []).append(person)

    created: List[Dict[str, Any]] = []
    for email, group in by_email.items():
        if len(group) < 2:
            continue
        anchor, *rest = group
        for other in rest:
            if await _already_linked(db, user_id, anchor.id, other.id):
                continue
            try:
                async with db.begin_nested():
                    await store.link_entities(
                        db, user_id, anchor.id, other.id,
                        relation_type="same_as", resolved_by=LinkResolvedBy.DETERMINISTIC,
                        confidence=1.0,
                    )
            except (SQLAlchemyError, ValueError):
                logger.exception(
                    "auto_link_by_email: failed to link %s <-> %s", anchor.id, other.id,
                )
                continue
            created.append({"entity_a": str(anchor.id), "entity_b": str(other.id), "email": email})
    return created


async def find_candidate_duplicates(
    db: AsyncSession, user_id: uuid.UUID, entity_type: Optional[EntityType] = None,
) -> List[Tuple[Entity, Entity]]:
    """Entities similar enough by embedding to be worth asking about, that
    aren't already linked. Each pair returned once regardless of which side
    of the similarity search surfaced it."""
    entity_types = [entity_type] if entity_type is not None else list(EntityType)
    seen_pairs: Set[frozenset] = set()
    candidates: List[Tuple[Entity, Entity]] = []

    for etype in entity_types:
        entities = await store.list_entities(db, user_id, entity_type=etype)
        for entity in entities:
            similar = await store.find_similar_entities(
                db, user_id, entity, max_distance=SIMILARITY_MAX_DISTANCE,
            )
            for other in similar:
                pair = frozenset({entity.id, other.id})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if await _already_linked(db, user_id, entity.id, other.id):
                    continue
                candidates.append((entity, other))
    return candidates


# ---------------------------------------------------------------------------
# Negotiation — the reactive trigger for the same Swarm mechanism
# domain_agent._ask_peer_agents uses proactively.
# ---------------------------------------------------------------------------

def _make_submit_same_as_verdict_tool(verdict: Dict[str, Any]):
    from strands import tool

    @tool
    def submit_same_as_verdict(same_entity: bool, confidence: float, reasoning: str) -> Dict[str, Any]:
        """Call this once you and the other agent agree — or determine you
        can't agree — on whether these are the same real-world entity.

        Args:
            same_entity: True if you both concluded they're the same entity.
            confidence: How confident the group is in this conclusion (0-1).
            reasoning: Brief explanation — shown to a human if this ends up
                needing validation.
        """
        verdict["same_entity"] = same_entity
        verdict["confidence"] = confidence
        verdict["reasoning"] = reasoning
        return {"recorded": True}

    return submit_same_as_verdict


async def negotiate_same_as(
    db: AsyncSession, user_id: uuid.UUID, entity_a: Entity, entity_b: Entity,
) -> Dict[str, Any]:
    """Scoped Swarm negotiation deciding whether two candidate entities are
    the same real-world entity. Returns {same_entity, confidence, reasoning}
    — same_entity=False/confidence=None if the swarm crashes or never
    concludes (caller treats that as "couldn't resolve", not "resolved: no")."""
    claims_a = await store.list_claims(db, user_id, entity_a.id, status=ClaimStatus.ACTIVE)
    claims_b = await store.list_claims(db, user_id, entity_b.id, status=ClaimStatus.ACTIVE)
    sources_a = sorted({c.source for c in claims_a})
    sources_b = sorted({c.source for c in claims_b})

    from strands import tool

    from app.services.agent.knowledge.swarm_negotiation import run_negotiation

    verdict: Dict[str, Any] = {"same_entity": False, "confidence": None, "reasoning": None}
    submit_same_as_verdict = _make_submit_same_as_verdict_tool(verdict)

    @tool
    async def view_claims(entity_label: str) -> List[Dict[str, Any]]:
        """View the active claims for entity 'a' or entity 'b'."""
        claims = claims_a if entity_label == "a" else claims_b
        return [{"source": c.source, "claim_text": c.claim_text} for c in claims]

    question = (
        f"¿'{entity_a.canonical_name}' (entidad 'a', fuentes: {sources_a}) y "
        f"'{entity_b.canonical_name}' (entidad 'b', fuentes: {sources_b}) son la misma "
        "persona/entidad en la vida real, o son entidades distintas que casualmente se "
        "parecen? Usá view_claims('a') y view_claims('b') para ver qué sabe cada fuente "
        "antes de opinar."
    )
    prompt_template = (
        "Sos un negociador de reconciliación de identidad, representando a las fuentes "
        "{sources}. " + question + " Coordiná con el otro agente presente. Cuando lleguen "
        "a una conclusión juntos — o determinen que no se puede resolver entre agentes — "
        "llamá a submit_same_as_verdict. No dejes la negociación sin esa llamada."
    )
    node_specs = [
        {
            "name": "entity_a_negotiator",
            "system_prompt": prompt_template.format(sources=sources_a),
            "tools": [view_claims, submit_same_as_verdict],
        },
        {
            "name": "entity_b_negotiator",
            "system_prompt": prompt_template.format(sources=sources_b),
            "tools": [view_claims, submit_same_as_verdict],
        },
    ]
    await run_negotiation(node_specs, question, log_context="negotiate_same_as")

    return verdict


# ---------------------------------------------------------------------------
# Confidence — the "solidity" metric
# ---------------------------------------------------------------------------

async def recompute_confidence(db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID) -> float:
    """Heuristic v1 for the knowledge base's "solidity" metric — deliberately
    simple and documented rather than tuned: confidence rises with
    independent corroborating sources and confirmed same_as links, and
    drops when there's an unresolved dispute. Phase 7 (observability) is
    where this gets revisited against real data."""
    claims = await store.list_claims(db, user_id, entity_id)
    active_sources = {c.source for c in claims if c.status == ClaimStatus.ACTIVE}
    has_dispute = any(c.status == ClaimStatus.DISPUTED for c in claims)
    has_user_confirmed = any(c.status == ClaimStatus.CONFIRMED_BY_USER for c in claims)
    same_as_links = [
        link for link in await store.list_links_for_entity(db, user_id, entity_id)
        if link.relation_type == "same_as"
    ]

    confidence = 0.5
    confidence += 0.15 * max(0, len(active_sources) - 1)
    confidence += 0.1 * len(same_as_links)
    if has_user_confirmed:
        confidence += 0.2
    if has_dispute:
        confidence -= 0.2

    return max(0.0, min(1.0, confidence))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def _find_open_reconciliation_question(
    db: AsyncSession, user_id: uuid.UUID, entity_a_id: uuid.UUID, entity_b_id: uuid.UUID,
):
    a_str, b_str = str(entity_a_id), str(entity_b_id)
    for q in await store.list_open_questions(db, user_id):
        if {q.context.get("entity_id"), q.context.get("candidate_entity_id")} == {a_str, b_str}:
            return q
    return None


async def run_reconciliation(
    db: AsyncSession, user_id: uuid.UUID, entity_type: Optional[EntityType] = None,
) -> Dict[str, Any]:
    """One reconciliation pass: deterministic auto-link, then scoped-Swarm
    negotiation for embedding-similar candidates (skipping any pair that
    already has an open question from a previous pass), then confidence
    recompute for every entity touched.

    Wired into KnowledgeAgentScheduler._run_cycle (app/services/agent/knowledge/scheduler.py,
    Phase 8) — runs once per user at the end of every knowledge cycle, after all domain
    agents for that cycle finish. Also callable manually via scripts/run_reconciliation.py.
    """
    # Email matching only ever applies to people — skip it when the caller
    # scoped this run to a different entity_type, matching the CLI's own
    # "limit to one entity type" promise.
    auto_linked: List[Dict[str, Any]] = []
    if entity_type is None or entity_type == EntityType.PERSON:
        auto_linked = await auto_link_by_email(db, user_id)
    candidates = await find_candidate_duplicates(db, user_id, entity_type=entity_type)

    negotiated: List[Dict[str, Any]] = []
    escalated: List[Dict[str, Any]] = []
    skipped_pending = 0
    touched: Set[uuid.UUID] = set()

    for link in auto_linked:
        touched.add(uuid.UUID(link["entity_a"]))
        touched.add(uuid.UUID(link["entity_b"]))

    for entity_a, entity_b in candidates:
        if await _find_open_reconciliation_question(db, user_id, entity_a.id, entity_b.id):
            skipped_pending += 1
            continue

        touched.update({entity_a.id, entity_b.id})
        verdict = await negotiate_same_as(db, user_id, entity_a, entity_b)

        try:
            async with db.begin_nested():
                if verdict["same_entity"] and (verdict["confidence"] or 0) >= SAME_AS_CONFIDENCE_THRESHOLD:
                    await store.link_entities(
                        db, user_id, entity_a.id, entity_b.id,
                        relation_type="same_as", resolved_by=LinkResolvedBy.SWARM,
                        confidence=verdict["confidence"],
                    )
                    negotiated.append({"entity_a": str(entity_a.id), "entity_b": str(entity_b.id)})
                else:
                    question = await store.raise_question(
                        db, user_id, "reconciliation_engine",
                        f"¿'{entity_a.canonical_name}' y '{entity_b.canonical_name}' son la misma entidad?",
                        context={"entity_id": str(entity_a.id), "candidate_entity_id": str(entity_b.id)},
                        target=QuestionTarget.HUMAN,
                        candidate_answer=verdict.get("reasoning"),
                        candidate_confidence=verdict.get("confidence"),
                    )
                    escalated.append({"question_id": str(question.id)})
        except (SQLAlchemyError, ValueError):
            logger.exception(
                "run_reconciliation: failed to record outcome for %s <-> %s", entity_a.id, entity_b.id,
            )
            continue

    for entity_id in touched:
        try:
            async with db.begin_nested():
                new_confidence = await recompute_confidence(db, user_id, entity_id)
                await store.update_entity_confidence(db, user_id, entity_id, new_confidence)
        except SQLAlchemyError:
            logger.exception("run_reconciliation: failed to recompute confidence for %s", entity_id)
            continue

    return {
        "auto_linked": len(auto_linked),
        "negotiated": len(negotiated),
        "escalated": len(escalated),
        "skipped_pending": skipped_pending,
        "entities_recomputed": len(touched),
    }
