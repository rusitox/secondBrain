"""Strands tool wrappers for all secondBrain agent tools.

Exposes a factory function ``make_agent_tools`` that injects the DB session,
user_id, timezone, and embedder into each tool via closures, returning a list
of Strands-compatible tool objects ready for an Agent.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from strands import tool

__all__ = ["make_agent_tools"]

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_HTTP_RESPONSE_CHAR_LIMIT = 8000
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def make_agent_tools(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_timezone: str = "UTC",
    embedder: Optional[Any] = None,
    parent_run_id: Optional[uuid.UUID] = None,
) -> List[Any]:
    """Factory that creates all agent tools with db/user_id injected via closure.

    Args:
        db: Async SQLAlchemy session scoped to the current request.
        user_id: UUID of the authenticated user.
        user_timezone: IANA timezone name used for calendar localisation.
        embedder: Optional Embedder instance required by memory tools.
        parent_run_id: This chat's own AgentRun id (see StrandsOrchestrator._build_agent),
            passed through so ask_domain_agents' negotiation traces as a sub-run of this
            chat rather than a disconnected row.

    Returns:
        List of Strands tool objects ready to pass to an Agent.
    """

    @tool
    async def search_memory(
        query: str,
        source: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the user's personal knowledge base using semantic similarity.

        Args:
            query: The natural-language search query.
            source: Optional platform filter — one of slack, outlook, teams, fathom, notion.
            top_k: Maximum number of results to return.
        """
        from app.services.agent.tools.memory_retriever import MemoryRetrieverTool

        if embedder is None:
            logger.warning("search_memory called without embedder — returning empty list")
            return []
        return await MemoryRetrieverTool(embedder).run(
            db, user_id, query=query, source=source, top_k=top_k
        )

    @tool
    async def list_tasks() -> List[Dict[str, Any]]:
        """List all pending commitments and action items for the user.
        """
        from app.services.agent.tools.task_manager import TaskManagerTool

        return await TaskManagerTool().list_pending(db, user_id)

    @tool
    async def get_calendar(
        date: Optional[str] = None,
        upcoming_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get the user's calendar events for a given date.

        Args:
            date: Target date in YYYY-MM-DD format. Defaults to today in UTC.
            upcoming_only: When True, exclude events that have already started.
        """
        from app.services.agent.tools.calendar_sync import CalendarSyncTool

        parsed_date: Optional[datetime] = None
        if date is not None:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        return await CalendarSyncTool().get_today_events(
            db,
            user_id,
            date=parsed_date,
            upcoming_only=upcoming_only,
            user_timezone=user_timezone,
        )

    @tool
    async def get_user_style() -> Dict[str, Any]:
        """Get the user's communication persona, tone guidelines, and heuristics.
        """
        from app.services.agent.tools.style_analyzer import StyleAnalyzerTool

        return await StyleAnalyzerTool().get_style(db, user_id)

    @tool
    async def search_learnings(
        query: str,
        entity_name: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the user's long-term distilled memory entries by semantic similarity.

        Args:
            query: The natural-language search query.
            entity_name: Optional entity name to filter results (e.g. a person or project).
            top_k: Maximum number of results to return.
        """
        from app.services.agent.tools.search_learnings import SearchLearningsTool

        if embedder is None:
            logger.warning("search_learnings called without embedder — returning empty list")
            return []
        return await SearchLearningsTool(embedder).run(
            db, user_id, query=query, entity_name=entity_name, top_k=top_k
        )

    @tool
    async def save_learning(
        content: str,
        importance: int = 3,
        source_type: str = "conversation",
        source_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a learning or insight to the user's long-term memory.

        Args:
            content: The learning or insight text to store.
            importance: Importance score from 1 (low) to 5 (high). Defaults to 3.
            source_type: Origin type of the learning (e.g. conversation, document).
            source_ref: Optional reference identifier for the source (e.g. a message ID).
        """
        from app.services.agent.tools.save_learning import SaveLearningTool

        if embedder is None:
            logger.warning("save_learning called without embedder — skipping")
            return {"saved": False, "reason": "no_embedder"}
        return await SaveLearningTool(embedder).run(
            db,
            user_id,
            content=content,
            importance=importance,
            source_type=source_type,
            source_ref=source_ref,
        )

    @tool
    async def get_sync_status() -> List[Dict[str, Any]]:
        """Get the last sync timestamp and status for each connected platform integration.
        """
        from app.services.agent.tools.sync_status import SyncStatusTool

        return await SyncStatusTool().get_status(db, user_id)

    @tool
    def get_current_datetime() -> str:
        """Get the current date and time in UTC ISO 8601 format.
        """
        return datetime.now(timezone.utc).isoformat()

    @tool
    async def query_knowledge(
        query: str, entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search the unified, cross-source knowledge base built by the domain
        agents — people, projects, topics, each with every source's claims and
        an aggregate confidence score you can cite and calibrate your certainty
        against. Prefer this over search_memory when the question is about a
        specific person, project, or topic the domain agents may have already
        consolidated.

        Args:
            query: Name or topic to search for.
            entity_type: Optional filter — one of person, project, initiative, topic, organization.
        """
        from app.models.entity import EntityType
        from app.services.agent.knowledge import resolution

        parsed_type: Optional[EntityType] = None
        if entity_type:
            try:
                parsed_type = EntityType(entity_type)
            except ValueError:
                return []
        return await resolution.consult_knowledge_base(db, user_id, query, entity_type=parsed_type)

    @tool
    async def get_pending_questions() -> List[Dict[str, Any]]:
        """Get open questions the domain agents couldn't resolve on their own
        and need you to ask the human. Each includes question_text and, when
        available, a candidate_answer — validate that with the user instead of
        asking cold. Only bring these up when natural in conversation, not
        forced into every reply.
        """
        from app.models.pending_question import QuestionTarget
        from app.services.agent.knowledge import store as knowledge_store

        questions = await knowledge_store.list_open_questions(db, user_id, target=QuestionTarget.HUMAN)
        return [
            {
                "question_id": str(q.id),
                "question_text": q.question_text,
                "candidate_answer": q.candidate_answer,
                "candidate_confidence": q.candidate_confidence,
            }
            for q in questions
        ]

    @tool
    async def confirm_pending_answer(
        question_id: str, answer_text: str, confirmed: bool = True,
    ) -> Dict[str, Any]:
        """Record the human's answer to a question from get_pending_questions —
        call this once they confirm or correct a candidate_answer. Closes the
        loop: a confirmed answer becomes a high-confidence claim (or a same_as
        link, for an "are these the same entity" question), and the question
        is marked resolved either way.

        Args:
            question_id: The question_id from get_pending_questions.
            answer_text: The human's answer, in their own words.
            confirmed: True if they confirmed/agreed, False if they said no —
                either way the question is closed, but only a confirmation
                writes a claim or link.
        """
        import uuid as _uuid

        from app.services.agent.knowledge import reconciliation

        try:
            parsed_question_id = _uuid.UUID(question_id)
        except ValueError as e:
            return {"error": f"invalid question_id {question_id!r}: {e}"}
        return await reconciliation.apply_question_answer(
            db, user_id, parsed_question_id, answer_text, confirmed,
        )

    @tool
    async def correct_knowledge(
        entity_id: str,
        correction: Optional[str] = None,
        claim_id: Optional[str] = None,
        other_entity_id: Optional[str] = None,
        same_entity: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Fix the knowledge graph right when the user tells you something in
        it is wrong — don't just note it for this reply, correct it so it
        stays fixed. This is what keeps the knowledge base alive: it updates
        from conversation, not only from ingestion. Always confirm out loud
        what you understood before calling this — it writes with full
        confidence (source="user"), no further review queue, unlike a domain
        agent's own claims.

        Pass whatever applies — combine them in one call if the user gave you
        both a fact correction and an identity correction:

        - Wrong fact: entity_id + correction (the corrected fact, in the
          user's own words) — becomes a new high-confidence claim. If the
          user pointed at a specific wrong claim from query_knowledge's
          claims list, also pass its claim_id — that claim gets marked
          disputed (kept for history, no longer treated as current fact).
        - Identity correction ("these are/aren't the same X"): entity_id +
          other_entity_id + same_entity (True to merge them as the same
          entity, False to undo a merge between them — including one the
          system made automatically and got wrong).

        Args:
            entity_id: The entity being corrected (from query_knowledge).
            correction: The corrected fact, in the user's own words.
            claim_id: A specific existing claim (from query_knowledge) the
                user says is wrong — gets marked disputed.
            other_entity_id: For an identity correction, the other entity_id.
            same_entity: Required together with other_entity_id — True to
                merge, False to unmerge.
        """
        import uuid as _uuid

        from sqlalchemy.exc import SQLAlchemyError

        from app.models.entity_claim import ClaimStatus
        from app.models.entity_link import LinkResolvedBy
        from app.services.agent.knowledge import reconciliation
        from app.services.agent.knowledge import store as knowledge_store

        try:
            parsed_entity_id = _uuid.UUID(entity_id)
        except ValueError as e:
            return {"error": f"invalid entity_id {entity_id!r}: {e}"}

        parsed_other_id = None
        if other_entity_id is not None:
            if same_entity is None:
                return {"error": "same_entity is required when other_entity_id is given"}
            try:
                parsed_other_id = _uuid.UUID(other_entity_id)
            except ValueError as e:
                return {"error": f"invalid other_entity_id {other_entity_id!r}: {e}"}

        parsed_claim_id = None
        if claim_id is not None:
            try:
                parsed_claim_id = _uuid.UUID(claim_id)
            except ValueError as e:
                return {"error": f"invalid claim_id {claim_id!r}: {e}"}

        result: Dict[str, Any] = {}
        touched_entity_ids = {parsed_entity_id}

        try:
            async with db.begin_nested():
                if parsed_claim_id is not None:
                    disputed = await knowledge_store.dispute_claim(
                        db, user_id, parsed_claim_id, entity_id=parsed_entity_id,
                    )
                    if disputed is None:
                        return {"error": f"claim {claim_id} not found on entity {entity_id}"}
                    result["disputed_claim_id"] = claim_id

                if correction:
                    claim = await knowledge_store.add_claim(
                        db, parsed_entity_id, user_id, source="user", claim_text=correction,
                        asserted_by_agent="user", status=ClaimStatus.CONFIRMED_BY_USER, confidence=1.0,
                    )
                    result["new_claim_id"] = str(claim.id)

                if parsed_other_id is not None:
                    touched_entity_ids.add(parsed_other_id)
                    if same_entity:
                        # link_entities has no uniqueness constraint of its own —
                        # skip creating a duplicate if the user is just re-confirming
                        # a merge that's already there.
                        if not await knowledge_store.links_exist(
                            db, user_id, parsed_entity_id, parsed_other_id, relation_type="same_as",
                        ):
                            await knowledge_store.link_entities(
                                db, user_id, parsed_entity_id, parsed_other_id,
                                relation_type="same_as", resolved_by=LinkResolvedBy.USER, confidence=1.0,
                            )
                        # The user may be overriding a reconciliation pass that
                        # already decided (wrongly) these were distinct — clear
                        # that stale not_same_as link so it doesn't contradict
                        # the merge just made, or keep suppressing this pair.
                        await knowledge_store.unlink_entities(
                            db, user_id, parsed_entity_id, parsed_other_id, relation_type="not_same_as",
                        )
                        result["linked"] = True
                    else:
                        removed = await knowledge_store.unlink_entities(
                            db, user_id, parsed_entity_id, parsed_other_id, relation_type="same_as",
                        )
                        result["unlinked"] = removed > 0

                if not result:
                    return {
                        "error": "nothing to do — pass correction, claim_id, or other_entity_id+same_entity",
                    }

                for eid in touched_entity_ids:
                    new_confidence = await reconciliation.recompute_confidence(db, user_id, eid)
                    await knowledge_store.update_entity_confidence(db, user_id, eid, new_confidence)
        except (SQLAlchemyError, ValueError) as e:
            logger.warning("correct_knowledge failed for entity_id=%s: %s", entity_id, e)
            return {"error": str(e)}

        return {"resolved": True, **result}

    @tool
    async def ask_domain_agents(entity_id: str, question: str) -> Dict[str, Any]:
        """Validate a doubt with the relevant domain agents before answering,
        instead of guessing or answering with stale/conflicting knowledge.

        Use this when query_knowledge doesn't give you a confident answer, or
        when different sources' claims about an entity conflict — never for
        routine questions the knowledge base already answers cleanly. This
        triggers a real negotiation between the domain agents that actually
        know something about the entity (a scoped Swarm, like a domain agent's
        own ask_peer_agents) and can take several seconds — worth it for a
        doubt that matters, not for every message.

        Args:
            entity_id: The entity_id from query_knowledge you have a doubt about.
            question: The specific doubt, framed so a domain agent can answer it.

        Returns {resolved, answer, confidence, peers_consulted, question_id}.
        resolved=False with an answer means the agents converged on a
        low-confidence or partial answer, still worth weighing; resolved=False
        with answer=None and peers_consulted=[] means nobody relevant was
        available — fall back to what query_knowledge already gave you, or
        tell the user honestly that you're not sure. Either way, if it isn't
        resolved, don't present the guess as settled fact.
        """
        import uuid as _uuid

        from app.services.agent.knowledge import domain_agent

        try:
            parsed_entity_id = _uuid.UUID(entity_id)
        except ValueError as e:
            return {"error": f"invalid entity_id {entity_id!r}: {e}"}
        # trigger defaults to RunTrigger.API on consult_domain_agents_for_orchestrator —
        # every orchestrator call is API-triggered, same as the chat run itself.
        return await domain_agent.consult_domain_agents_for_orchestrator(
            db, user_id, parsed_entity_id, question, parent_run_id=parent_run_id,
        )

    tools = [
        search_memory,
        list_tasks,
        get_calendar,
        get_user_style,
        search_learnings,
        save_learning,
        get_sync_status,
        get_current_datetime,
        query_knowledge,
        ask_domain_agents,
        get_pending_questions,
        confirm_pending_answer,
        correct_knowledge,
    ]

    from app.core.config import get_settings

    settings = get_settings()

    if settings.brave_search_api_key:
        @tool
        async def web_search(query: str, count: int = 5) -> List[Dict[str, str]]:
            """Search the public web using Brave Search. Use this for questions
            about current events, facts outside the user's personal knowledge
            base, or anything not covered by search_memory/search_learnings.

            Args:
                query: The search query.
                count: Number of results to return (1-10). Defaults to 5.
            """
            capped_count = max(1, min(count, 10))
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                    resp = await client.get(
                        _BRAVE_SEARCH_URL,
                        params={"q": query, "count": capped_count},
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": settings.brave_search_api_key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPError as e:
                logger.warning("web_search: request failed for query=%r: %s", query, e)
                return []

            results = data.get("web", {}).get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("description", ""),
                }
                for r in results[:capped_count]
            ]

        tools.append(web_search)

    allowed_domains = {
        d.strip().lower()
        for d in settings.http_request_allowed_domains.split(",")
        if d.strip()
    }
    if allowed_domains:
        @tool
        async def http_request(url: str) -> str:
            """Fetch the contents of a URL via HTTP GET. Only works for a
            pre-approved allowlist of domains configured by the operator —
            use this to look up a specific known page (e.g. documentation),
            not to browse arbitrary user-supplied links.

            Args:
                url: The full URL to fetch (must be http:// or https://).
            """
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https"):
                return f"Error: unsupported URL scheme {parsed.scheme!r}. Only http/https are allowed."
            if hostname not in allowed_domains:
                logger.warning("http_request: blocked disallowed domain=%r for url=%r", hostname, url)
                return f"Error: domain {hostname!r} is not in the allowed list."

            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("http_request: request failed for url=%r: %s", url, e)
                return f"Error: request failed — {e}"

            content_type = resp.headers.get("content-type", "")
            if not any(t in content_type for t in ("text/", "application/json", "application/xml")):
                return f"Error: unsupported content-type {content_type!r}."

            return resp.text[:_HTTP_RESPONSE_CHAR_LIMIT]

        tools.append(http_request)

    logger.info("make_agent_tools: created %d tools for user=%s", len(tools), user_id)
    return tools
