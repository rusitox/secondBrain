"""Domain agent factory — Phase 1 reference implementation.

See specs/plan-multi-agent-knowledge.md. A domain agent's mandate: read its
own source's unprocessed Documents, propose entities/claims into the shared
knowledge store, and walk the resolution ladder when something doesn't fit
— consult the knowledge base, then peer agents (if any are registered),
then propose a candidate for human validation. A blank question to the
human is the last resort, never the first.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.pending_question import QuestionTarget
from app.services.agent.knowledge import resolution, store

logger = logging.getLogger(__name__)

# Sources with a registered domain agent. Phase 2+ appends to this as each
# connector gets its own agent. With only "slack" registered, ask_peer_agents
# correctly finds nobody to negotiate with yet and every doubt falls through
# to human validation — that's the expected Phase 1 behavior, not a bug.
REGISTERED_SOURCES: List[str] = ["slack"]

_SOURCE_GUIDANCE: Dict[str, str] = {
    "slack": (
        "Los documentos son mensajes de Slack (canales y DMs). Prestá atención a "
        "menciones de personas (@usuario o nombres propios), proyectos, y decisiones "
        "tomadas en el hilo."
    ),
}

DOMAIN_AGENT_SYSTEM_PROMPT = """\
Sos un agente de dominio del sistema de conocimiento unificado, responsable de {source}.

Tu mandato:
1. Procesá los documentos no leídos de tu fuente con get_unprocessed_documents.
2. Por cada documento, identificá entidades relevantes (personas, proyectos, \
iniciativas, temas) y qué afirma el documento sobre ellas.
3. Antes de crear una entidad nueva, usá find_or_create_entity — puede que ya exista.
4. Guardá cada afirmación con add_claim, citando tu fuente y tu confianza real (0-1).
5. Marcá el documento como procesado con mark_document_processed, incluso si no \
encontraste nada relevante en él — así no lo volvés a leer en el próximo ciclo.

Escalera de resolución de dudas — nunca le preguntes al humano directo:
1. Si algo no te cierra, primero consultá el conocimiento existente con \
consult_knowledge_base.
2. Si sigue sin resolverse, consultá a tus pares con ask_peer_agents.
3. Si ninguno de los dos resuelve la duda, usá escalate_or_validate. Si llegaste a \
una respuesta parcial en los pasos 1-2, pasala como candidate_answer para que el \
humano la valide en vez de responder una pregunta en blanco.

{source_guidance}

Priorizá la solidez del conocimiento por sobre la velocidad: mejor un claim con \
confianza baja y correctamente marcada como tal, que inventar certeza."""


def make_domain_agent(source: str, db: AsyncSession, user_id: uuid.UUID) -> Any:
    """Build a Strands Agent scoped to one data source.

    A new agent is built per invocation — no shared mutable state between
    concurrent extraction runs (same rationale as StrandsOrchestrator).
    """
    from strands import Agent, tool

    from app.services.agent.strands_model import build_openai_model

    model = build_openai_model()

    @tool
    async def get_unprocessed_documents(limit: int = 20) -> List[Dict[str, Any]]:
        """Get up to `limit` documents from this source that haven't been processed yet."""
        docs = await store.get_unprocessed_documents(db, user_id, source, limit=limit)
        return [
            {
                "document_id": str(d.id),
                "content": d.content,
                "source_id": d.source_id,
                "metadata": d.metadata_,
            }
            for d in docs
        ]

    @tool
    async def mark_document_processed(document_id: str) -> Dict[str, Any]:
        """Mark a document as processed so it isn't re-read on the next run."""
        await store.mark_document_processed(db, user_id, uuid.UUID(document_id), source)
        return {"marked": True}

    @tool
    async def find_or_create_entity(
        entity_type: str,
        name: str,
        aliases: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Find an existing entity by name/alias, or create a new one if none matches.

        Args:
            entity_type: One of person, project, initiative, topic, organization.
            name: The entity's name as it appears in this document.
            aliases: Other names this entity might be known by.
            attributes: Free-form extra facts (e.g. {"email": "..."}).
        """
        try:
            parsed_type = EntityType(entity_type)
        except ValueError:
            return {"error": f"invalid entity_type {entity_type!r}"}
        entity, created = await resolution.find_or_create_entity(
            db, user_id, parsed_type, name, aliases=aliases, attributes=attributes,
        )
        return {
            "entity_id": str(entity.id),
            "created": created,
            "canonical_name": entity.canonical_name,
        }

    @tool
    async def add_claim(
        entity_id: str,
        claim_text: str,
        confidence: float = 0.5,
        source_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record what this document asserts about an entity, with your real confidence (0-1)."""
        claim = await store.add_claim(
            db, uuid.UUID(entity_id), user_id, source, claim_text,
            asserted_by_agent=f"{source}_domain_agent",
            source_ref=source_ref, confidence=confidence,
        )
        return {"claim_id": str(claim.id)}

    @tool
    async def consult_knowledge_base(
        query: str, entity_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search existing entities/claims before treating something as unknown.

        Step 1 of the resolution ladder — always try this before ask_peer_agents
        or escalate_or_validate."""
        parsed_type: Optional[EntityType] = None
        if entity_type:
            try:
                parsed_type = EntityType(entity_type)
            except ValueError:
                return []
        return await resolution.consult_knowledge_base(db, user_id, query, entity_type=parsed_type)

    @tool
    async def ask_peer_agents(entity_id: str, question: str) -> Dict[str, Any]:
        """Ask other domain agents for help resolving a doubt about an entity.

        Step 2 of the resolution ladder. Only agents whose source already holds
        a claim about this entity are consulted — returns
        {resolved, answer, confidence, peers_consulted}. peers_consulted=[] means
        nobody relevant was available; fall through to escalate_or_validate."""
        return await _ask_peer_agents(db, user_id, source, uuid.UUID(entity_id), question)

    @tool
    async def escalate_or_validate(
        question_text: str,
        candidate_answer: Optional[str] = None,
        candidate_confidence: Optional[float] = None,
        entity_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Last resort — steps 3/4 of the resolution ladder.

        Always pass candidate_answer/candidate_confidence if steps 1-2 produced
        anything, even a low-confidence guess, so the human validates instead of
        answering a blind question."""
        context: Dict[str, Any] = {"entity_id": entity_id} if entity_id else {}
        question = await store.raise_question(
            db, user_id, f"{source}_domain_agent", question_text,
            context=context, target=QuestionTarget.HUMAN,
            candidate_answer=candidate_answer, candidate_confidence=candidate_confidence,
        )
        return {"question_id": str(question.id)}

    tools = [
        get_unprocessed_documents,
        mark_document_processed,
        find_or_create_entity,
        add_claim,
        consult_knowledge_base,
        ask_peer_agents,
        escalate_or_validate,
    ]

    system_prompt = DOMAIN_AGENT_SYSTEM_PROMPT.format(
        source=source, source_guidance=_SOURCE_GUIDANCE.get(source, ""),
    )

    return Agent(
        model=model, tools=tools, system_prompt=system_prompt, name=f"{source}_domain_agent",
    )


async def run_domain_agent(
    source: str,
    db: AsyncSession,
    user_id: uuid.UUID,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """Entry point for the sync scheduler (or a manual trigger, Phase 1): process
    one batch of unprocessed documents for this source."""
    agent = make_domain_agent(source, db, user_id)
    task = (
        f"Procesá hasta {batch_size} documentos no leídos de {source} siguiendo tu mandato. "
        "Si no hay documentos pendientes, no hagas nada."
    )
    result = await agent.invoke_async(task)
    logger.info("run_domain_agent: source=%s user=%s done", source, user_id)
    return {"source": source, "summary": str(result)}


# ---------------------------------------------------------------------------
# ask_peer_agents — scoped Swarm negotiation (step 2 of the resolution ladder)
# ---------------------------------------------------------------------------

def _make_submit_verdict_tool(verdict: Dict[str, Any]):
    """Build the tool negotiator agents call to conclude a swarm negotiation.

    Separated out from _ask_peer_agents so the mutation logic is unit-testable
    without spinning up a real Agent/Swarm.
    """
    from strands import tool

    @tool
    def submit_verdict(resolved: bool, answer: str, confidence: float) -> Dict[str, Any]:
        """Call this once the negotiation reaches a conclusion — either agreement
        or a determination that it can't be resolved between agents.

        Args:
            resolved: Whether the group reached a conclusion.
            answer: The conclusion (or explanation of why it couldn't be reached).
            confidence: How confident the group is in `answer` (0-1).
        """
        verdict["resolved"] = resolved
        verdict["answer"] = answer
        verdict["confidence"] = confidence
        return {"recorded": True}

    return submit_verdict


async def _ask_peer_agents(
    db: AsyncSession,
    user_id: uuid.UUID,
    asking_source: str,
    entity_id: uuid.UUID,
    question: str,
) -> Dict[str, Any]:
    """Negotiate a doubt with the peer agents that actually have something to
    say about this entity — a scoped Swarm, never every registered source."""
    no_peers_result: Dict[str, Any] = {
        "resolved": False, "answer": None, "confidence": None, "peers_consulted": [],
    }

    peer_sources = [s for s in REGISTERED_SOURCES if s != asking_source]
    if not peer_sources:
        return no_peers_result

    # Only consult agents whose source already holds a claim about this
    # entity — no point negotiating with someone with nothing to contribute.
    claims = await store.list_claims(db, entity_id)
    relevant_sources = [s for s in peer_sources if any(c.source == s for c in claims)]
    if not relevant_sources:
        return no_peers_result

    entity = await store.get_entity(db, entity_id)
    entity_name = entity.canonical_name if entity is not None else str(entity_id)

    from strands import Agent, tool
    from strands.multiagent import Swarm

    from app.services.agent.strands_model import build_openai_model

    verdict: Dict[str, Any] = {"resolved": False, "answer": None, "confidence": None}
    submit_verdict = _make_submit_verdict_tool(verdict)

    @tool
    async def view_claims(claim_source: str) -> List[Dict[str, Any]]:
        """View this entity's claims from a specific source."""
        all_claims = await store.list_claims(db, entity_id)
        return [
            {"claim_text": c.claim_text, "confidence": c.confidence}
            for c in all_claims if c.source == claim_source
        ]

    model = build_openai_model()
    negotiator_prompt_template = (
        "Sos un negociador que representa a la fuente '{src}' en una duda sobre la "
        f"entidad '{entity_name}'. Otro agente pregunta: {question}\n\n"
        "Usá view_claims para ver qué sabe tu fuente sobre esta entidad. Si podés "
        "aportar algo relevante, hacelo. Coordiná con el otro agente presente — si "
        "entre los dos llegan a una conclusión, o si determinás que no hay forma de "
        "resolverlo entre agentes, llamá a submit_verdict. No dejes la negociación "
        "sin una llamada a submit_verdict."
    )

    nodes = [
        Agent(
            model=model,
            tools=[view_claims, submit_verdict],
            system_prompt=negotiator_prompt_template.format(src=src),
            name=f"{src}_negotiator",
        )
        for src in [asking_source, *relevant_sources]
    ]

    swarm = Swarm(nodes, max_handoffs=6, max_iterations=6)
    try:
        await swarm.invoke_async(question)
    except Exception:
        logger.exception("ask_peer_agents: swarm negotiation failed for entity=%s", entity_id)
        return {**no_peers_result, "peers_consulted": relevant_sources}

    return {**verdict, "peers_consulted": relevant_sources}
