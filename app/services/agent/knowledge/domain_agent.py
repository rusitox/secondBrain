"""Domain agent factory — one Strands Agent per data source.

See specs/plan-multi-agent-knowledge.md. A domain agent's mandate: read its
own source's unprocessed Documents, propose entities/claims into the shared
knowledge store, and walk the resolution ladder when something doesn't fit
— consult the knowledge base, then peer agents (if any are registered),
then propose a candidate for human validation. A blank question to the
human is the last resort, never the first.

Phase 1 built the pattern against Slack; Phase 2 (specs/plan-multi-agent-
knowledge.md) replicates it to Outlook/Teams/Fathom purely by registering
the source and adding its prompt guidance below — make_domain_agent itself
has no source-specific branching.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.pending_question import QuestionTarget, ResolvedBy
from app.services.agent.knowledge import resolution, store

logger = logging.getLogger(__name__)

# Sources with a registered domain agent. Phase 6 (I+D via MCP) appends to
# this later. ask_peer_agents only negotiates with sources listed here — a
# source with no domain agent yet simply can't be consulted.
REGISTERED_SOURCES: List[str] = ["slack", "outlook", "teams", "fathom", "notion"]

_SOURCE_GUIDANCE: Dict[str, str] = {
    "slack": (
        "Los documentos son mensajes de Slack (canales y DMs). Prestá atención a "
        "menciones de personas (@usuario o nombres propios), proyectos, y decisiones "
        "tomadas en el hilo."
    ),
    "outlook": (
        "Los documentos son emails y eventos de calendario de Outlook — fijate en "
        "metadata.type ('email' o 'calendar_event') para saber cuál es cuál. El "
        "remitente/organizador y los asistentes vienen como direcciones de email en "
        "metadata (author, attendees), no como nombres. Usá ese email como atributo "
        "(ej. {\"email\": \"...\"}) al crear o encontrar la entidad persona — es una "
        "señal fuerte para más adelante saber si es la misma persona que aparece en "
        "otra fuente."
    ),
    "teams": (
        "Los documentos son mensajes de Teams (chats 1:1 y grupales). A diferencia de "
        "Outlook, metadata.author acá es el nombre para mostrar de quien envió el "
        "mensaje, no un email — no asumas que es una dirección de correo. metadata "
        "también trae chat_topic y chat_type (oneOnOne/group) como contexto adicional."
    ),
    "fathom": (
        "Los documentos son transcripciones de reuniones grabadas por Fathom — texto "
        "largo, potencialmente con etiquetas de orador si la transcripción las trae. "
        "metadata solo tiene title, date y recording_url — no hay lista estructurada "
        "de participantes, así que identificá a los asistentes leyendo la transcripción."
    ),
    "notion": (
        "Los documentos son páginas o filas de bases de datos de Notion — metadata.type "
        "distingue 'notion_page' de 'notion_database_item'. metadata.author es quien "
        "editó por última vez la página, no necesariamente alguien mencionado en el "
        "contenido — no lo confundas con las personas de las que habla el documento. "
        "Este agente es de solo lectura hacia el conocimiento compartido: nunca escribe "
        "de vuelta a Notion, eso lo maneja NotionSync por separado."
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


def make_domain_agent(
    source: str, db: AsyncSession, user_id: uuid.UUID, embedder: Optional[Any] = None,
) -> Any:
    """Build a Strands Agent scoped to one data source.

    A new agent is built per invocation — no shared mutable state between
    concurrent extraction runs (same rationale as StrandsOrchestrator).

    Uses SequentialToolExecutor: Strands runs multiple tool calls from one
    LLM turn concurrently by default, but every tool here closes over the
    same AsyncSession, and AsyncSession is not safe for concurrent use from
    more than one task at a time. Sequential execution is required, not an
    optimization.

    embedder is optional (None in most tests) — when given, newly-created
    entities get embedded so Phase 4's reconciliation can find cross-source
    duplicates by similarity.
    """
    from strands import Agent, tool
    from strands.tools.executors import SequentialToolExecutor

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
        try:
            async with db.begin_nested():
                await store.mark_document_processed(db, user_id, uuid.UUID(document_id), source)
        except (SQLAlchemyError, ValueError) as e:
            logger.warning("mark_document_processed failed for document_id=%s: %s", document_id, e)
            return {"error": str(e)}
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
        try:
            async with db.begin_nested():
                entity, created = await resolution.find_or_create_entity(
                    db, user_id, parsed_type, name, aliases=aliases, attributes=attributes,
                    embedder=embedder,
                )
        except SQLAlchemyError as e:
            logger.warning("find_or_create_entity failed for name=%r: %s", name, e)
            return {"error": str(e)}
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
        try:
            async with db.begin_nested():
                claim = await store.add_claim(
                    db, uuid.UUID(entity_id), user_id, source, claim_text,
                    asserted_by_agent=f"{source}_domain_agent",
                    source_ref=source_ref, confidence=confidence,
                )
        except (SQLAlchemyError, ValueError) as e:
            logger.warning("add_claim failed for entity_id=%s: %s", entity_id, e)
            return {"error": str(e)}
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
        {resolved, answer, confidence, peers_consulted, question_id}.
        peers_consulted=[] means nobody relevant was available; fall through to
        escalate_or_validate yourself instead. Otherwise this already recorded
        the outcome (resolved or escalated to the human) — you don't need to
        call escalate_or_validate again for the same doubt."""
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
        try:
            async with db.begin_nested():
                question = await store.raise_question(
                    db, user_id, f"{source}_domain_agent", question_text,
                    context=context, target=QuestionTarget.HUMAN,
                    candidate_answer=candidate_answer, candidate_confidence=candidate_confidence,
                )
        except SQLAlchemyError as e:
            logger.warning("escalate_or_validate failed: %s", e)
            return {"error": str(e)}
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
        tool_executor=SequentialToolExecutor(),
    )


async def run_domain_agent(
    source: str,
    db: AsyncSession,
    user_id: uuid.UUID,
    batch_size: int = 20,
    embedder: Optional[Any] = None,
) -> Dict[str, Any]:
    """Entry point for the sync scheduler (or a manual trigger, Phase 1): process
    one batch of unprocessed documents for this source."""
    agent = make_domain_agent(source, db, user_id, embedder=embedder)
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


async def _find_open_question_for_entity(
    db: AsyncSession, user_id: uuid.UUID, entity_id: uuid.UUID
):
    """Find an already-open question about this entity, if any.

    The rate-limit the plan's own risk section requires: a batch that
    processes several documents mentioning the same ambiguous entity must
    not spin up a fresh Swarm negotiation (or duplicate human question) for
    every single one of them.
    """
    entity_id_str = str(entity_id)
    for q in await store.list_open_questions(db, user_id):
        if q.context.get("entity_id") == entity_id_str:
            return q
    return None


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
        "resolved": False, "answer": None, "confidence": None,
        "peers_consulted": [], "question_id": None,
    }

    peer_sources = [s for s in REGISTERED_SOURCES if s != asking_source]
    if not peer_sources:
        return no_peers_result

    # Only consult agents whose source already holds an ACTIVE claim about
    # this entity — no point negotiating with someone with nothing to
    # contribute, and a DISPUTED/SUPERSEDED claim must not be treated as
    # settled fact during negotiation.
    claims = await store.list_claims(db, user_id, entity_id, status=ClaimStatus.ACTIVE)
    relevant_sources = [s for s in peer_sources if any(c.source == s for c in claims)]
    if not relevant_sources:
        return no_peers_result

    existing = await _find_open_question_for_entity(db, user_id, entity_id)
    if existing is not None:
        return {
            "resolved": False,
            "answer": existing.candidate_answer,
            "confidence": existing.candidate_confidence,
            "peers_consulted": [],
            "question_id": str(existing.id),
        }

    entity = await store.get_entity(db, user_id, entity_id)
    entity_name = entity.canonical_name if entity is not None else str(entity_id)

    pending = await store.raise_question(
        db, user_id, f"{asking_source}_domain_agent", question,
        context={"entity_id": str(entity_id)}, target=QuestionTarget.PEER_AGENTS,
    )

    from strands import Agent, tool
    from strands.multiagent import Swarm
    from strands.tools.executors import SequentialToolExecutor

    from app.services.agent.strands_model import build_openai_model

    verdict: Dict[str, Any] = {"resolved": False, "answer": None, "confidence": None}
    submit_verdict = _make_submit_verdict_tool(verdict)

    @tool
    async def view_claims(claim_source: str) -> List[Dict[str, Any]]:
        """View this entity's active claims from a specific source."""
        all_claims = await store.list_claims(db, user_id, entity_id, status=ClaimStatus.ACTIVE)
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
            tool_executor=SequentialToolExecutor(),
        )
        for src in [asking_source, *relevant_sources]
    ]

    swarm = Swarm(nodes, max_handoffs=6, max_iterations=6)
    try:
        await swarm.invoke_async(question)
    except Exception:
        logger.exception("ask_peer_agents: swarm negotiation failed for entity=%s", entity_id)

    # Whatever the outcome, the question is resolved one way or another —
    # never left dangling on the hope that the caller's next turn follows up.
    if verdict["resolved"]:
        await store.resolve_question(
            db, user_id, pending.id, ResolvedBy.PEER_SWARM, answer_text=verdict["answer"],
        )
    else:
        await store.escalate_to_human(
            db, user_id, pending.id,
            candidate_answer=verdict["answer"], candidate_confidence=verdict["confidence"],
        )

    return {**verdict, "peers_consulted": relevant_sources, "question_id": str(pending.id)}
