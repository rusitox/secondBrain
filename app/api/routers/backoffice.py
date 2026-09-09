"""Knowledge-system backoffice API (specs/plan-knowledge-backoffice.md, Phase 4).

POST /backoffice/agents/{agent_key}/run — trigger a manual run of one agent
GET  /backoffice/agents — list every configurable agent's effective config
GET  /backoffice/agents/{agent_key} — one agent's effective config
PUT  /backoffice/agents/{agent_key} — save an override (partial — only given fields change)
DELETE /backoffice/agents/{agent_key}/overrides — revert to code defaults

GET  /backoffice/tools — the tool catalog, optionally scoped to one agent_key

GET    /backoffice/mcp-servers — list the user's registered MCP servers
POST   /backoffice/mcp-servers — register one
GET    /backoffice/mcp-servers/{server_id} — one server
PUT    /backoffice/mcp-servers/{server_id} — update it
DELETE /backoffice/mcp-servers/{server_id} — remove it
POST   /backoffice/mcp-servers/{server_id}/test — connect and list its tools

GET /backoffice/runs — list agent runs (filter by agent_key/status/run_type/top_level)
GET /backoffice/runs/{run_id} — one run, its events, and any sub-runs

GET  /backoffice/graph/entities — list/search entities (X-Total-Count response header)
GET  /backoffice/graph/entities/{entity_id} — one entity with claims + links
GET  /backoffice/graph/links — every entity link for the user, for graph-wide rendering
GET  /backoffice/graph/claims — every claim for the user (filter by source/status)
GET  /backoffice/graph/questions — pending questions (filter by status/target)
POST /backoffice/graph/questions/{question_id}/answer — answer, closing the loop
POST /backoffice/graph/questions/{question_id}/dismiss — dismiss without an answer

Every route is scoped to current_user_id — the same 404-for-not-found-or-not-yours
pattern as commitments.py/integrations.py, since a knowledge-backoffice row leaking
across users would be a much worse mistake than a 403 would have been.
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.backoffice import (
    AgentConfigRead,
    AgentConfigUpdate,
    AgentRunDetail,
    AgentRunEventRead,
    AgentRunSummary,
    AnswerQuestionRequest,
    ClaimRead,
    EntityDetail,
    EntityLinkRead,
    EntitySummary,
    McpServerCreate,
    McpServerRead,
    McpServerTestResult,
    McpServerUpdate,
    PendingQuestionRead,
    ToolInfoRead,
)
from app.models.agent_run import RunStatus, RunTrigger, RunType
from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.pending_question import QuestionStatus, QuestionTarget, ResolvedBy
from app.services import mcp_server_service
from app.services.agent import agent_config_service, run_query_service, tool_registry
from app.services.agent.knowledge import domain_agent, rd_agent, reconciliation, store

router = APIRouter(prefix="/backoffice", tags=["backoffice"])


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _default_prompt_for(agent_key: str) -> str:
    if agent_key == "rd":
        return rd_agent.RD_AGENT_SYSTEM_PROMPT
    if agent_key == "orchestrator":
        return "(dynamically composed per request — see StrandsOrchestrator._build_agent)"
    return domain_agent._default_system_prompt(agent_key)


async def _read_agent_config(db: AsyncSession, user_id: uuid.UUID, agent_key: str) -> AgentConfigRead:
    # One query, not two: get_config_row() + effective_config_from_row()
    # instead of get_effective_config() (which would re-fetch the row
    # itself) — list_agents calls this once per KNOWN_AGENT_KEYS entry, so
    # the duplicate query would otherwise double every page load's query count.
    row = await agent_config_service.get_config_row(db, user_id, agent_key)
    config = agent_config_service.effective_config_from_row(
        row, default_system_prompt=_default_prompt_for(agent_key),
    )
    return AgentConfigRead(
        agent_key=agent_key,
        enabled=config.enabled,
        model_id=config.model_id,
        system_prompt=config.system_prompt,
        enabled_tools=config.enabled_tools,
        mcp_server_ids=config.mcp_server_ids,
        params=config.params,
        has_override=row is not None,
    )


@router.get("/agents", response_model=List[AgentConfigRead])
async def list_agents(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[AgentConfigRead]:
    return [
        await _read_agent_config(db, current_user_id, key)
        for key in agent_config_service.KNOWN_AGENT_KEYS
    ]


@router.get("/agents/{agent_key}", response_model=AgentConfigRead)
async def get_agent(
    agent_key: str,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigRead:
    if agent_key not in agent_config_service.KNOWN_AGENT_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent_key")
    return await _read_agent_config(db, current_user_id, agent_key)


@router.put("/agents/{agent_key}", response_model=AgentConfigRead)
async def update_agent(
    agent_key: str,
    data: AgentConfigUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigRead:
    if agent_key not in agent_config_service.KNOWN_AGENT_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent_key")
    update_fields = data.model_dump(exclude_unset=True)
    await agent_config_service.upsert_agent_config(
        db, current_user_id, agent_key,
        enabled=update_fields.get("enabled"),
        model_id=update_fields.get("model_id", agent_config_service.UNSET),
        system_prompt=update_fields.get("system_prompt", agent_config_service.UNSET),
        enabled_tools=update_fields.get("enabled_tools", agent_config_service.UNSET),
        mcp_server_ids=update_fields.get("mcp_server_ids"),
        params=update_fields.get("params"),
    )
    return await _read_agent_config(db, current_user_id, agent_key)


@router.delete("/agents/{agent_key}/overrides", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_overrides(
    agent_key: str,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await agent_config_service.get_config_row(db, current_user_id, agent_key)
    if row is not None:
        await agent_config_service.delete_agent_config(db, row)


@router.post("/agents/{agent_key}/run", response_model=AgentRunSummary, status_code=status.HTTP_200_OK)
async def run_agent_now(
    agent_key: str,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AgentRunSummary:
    """Runs synchronously — the HTTP response waits for the agent to finish
    (a domain-agent batch typically takes on the order of tens of seconds).
    A background-job queue would let this return immediately with just a
    run_id, but nothing in this codebase has one yet (KnowledgeAgentScheduler
    runs are the closest precedent, and those aren't request-triggered
    either); adding one is out of scope for this endpoint alone.
    """
    if agent_key not in agent_config_service.KNOWN_AGENT_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent_key")
    if agent_key == "orchestrator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="orchestrator isn't run this way — use POST /agent/query",
        )

    # run_domain_agent/run_rd_domain_agent don't return their run_id (their
    # return shape is locked in by tests predating tracing), so the run they
    # just created is recovered afterward as "the most recent one for this
    # agent_key" — but only once a before/after row-count diff confirms a
    # new row actually landed. Comparing against before_count instead of
    # e.g. a started_at timestamp sidesteps clock-precision issues entirely
    # (SQLite's CURRENT_TIMESTAMP truncates to whole seconds, which made an
    # earlier timestamp-threshold version of this check flaky) and is what
    # actually matters: without it, an agent with prior run history that's
    # now skipped (disabled via config, or 'rd' with no MCP configured)
    # would return that OLD row as if it were this call's result — a false
    # 200 with stale data, not just a missed 409.
    before_count = await run_query_service.count_runs(db, current_user_id, agent_key=agent_key)
    if agent_key == "rd":
        await rd_agent.run_rd_domain_agent(db, current_user_id, trigger=RunTrigger.MANUAL)
    else:
        await domain_agent.run_domain_agent(agent_key, db, current_user_id, trigger=RunTrigger.MANUAL)

    after_count = await run_query_service.count_runs(db, current_user_id, agent_key=agent_key)
    if after_count == before_count:
        # Reachable when the agent was disabled via config, 'rd' has no MCP
        # server configured, or (rarely) tracing.start_run itself silently
        # failed — tracing.py never raises, so a genuine run can complete
        # with no AgentRun row at all.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No run was recorded for '{agent_key}' — it may be disabled via agent config, "
                   "or (for 'rd') have no MCP server configured.",
        )
    recent = await run_query_service.list_runs(db, current_user_id, agent_key=agent_key, limit=1)
    return AgentRunSummary.model_validate(recent[0])


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@router.get("/tools", response_model=List[ToolInfoRead])
async def list_tools(
    agent_key: Optional[str] = Query(None),
    _: uuid.UUID = Depends(get_current_user_id),
) -> List[ToolInfoRead]:
    if agent_key is not None and agent_key not in agent_config_service.KNOWN_AGENT_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent_key")
    keys = [agent_key] if agent_key else agent_config_service.KNOWN_AGENT_KEYS
    configurable_names = {
        t.name for key in keys for t in tool_registry.configurable_tools_for_agent(key)
    }
    seen: List[ToolInfoRead] = []
    seen_names = set()
    for key in keys:
        for t in tool_registry.tools_for_agent(key):
            if t.name in seen_names:
                continue
            seen_names.add(t.name)
            seen.append(ToolInfoRead(
                name=t.name, description=t.description, category=t.category,
                configurable=t.name in configurable_names,
            ))
    return seen


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

def _mcp_server_read(server) -> McpServerRead:
    return McpServerRead(
        id=server.id, name=server.name, url=server.url, auth_header=server.auth_header,
        enabled=server.enabled, allowed_tools=server.allowed_tools, rejected_tools=server.rejected_tools,
        last_checked_at=server.last_checked_at, last_status=server.last_status,
        discovered_tools=server.discovered_tools, has_api_key=bool(server.api_key_encrypted),
        created_at=server.created_at, updated_at=server.updated_at,
    )


@router.get("/mcp-servers", response_model=List[McpServerRead])
async def list_mcp_servers(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[McpServerRead]:
    servers = await mcp_server_service.list_mcp_servers(db, current_user_id)
    return [_mcp_server_read(s) for s in servers]


@router.post("/mcp-servers", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    data: McpServerCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> McpServerRead:
    server = await mcp_server_service.create_mcp_server(
        db, current_user_id, name=data.name, url=data.url, auth_header=data.auth_header,
        api_key=data.api_key, enabled=data.enabled, allowed_tools=data.allowed_tools,
        rejected_tools=data.rejected_tools,
    )
    return _mcp_server_read(server)


async def _get_owned_mcp_server(db: AsyncSession, user_id: uuid.UUID, server_id: uuid.UUID):
    server = await mcp_server_service.get_mcp_server(db, user_id, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return server


@router.get("/mcp-servers/{server_id}", response_model=McpServerRead)
async def get_mcp_server(
    server_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> McpServerRead:
    server = await _get_owned_mcp_server(db, current_user_id, server_id)
    return _mcp_server_read(server)


@router.put("/mcp-servers/{server_id}", response_model=McpServerRead)
async def update_mcp_server(
    server_id: uuid.UUID,
    data: McpServerUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> McpServerRead:
    server = await _get_owned_mcp_server(db, current_user_id, server_id)
    updated = await mcp_server_service.update_mcp_server(
        db, server, name=data.name, url=data.url, auth_header=data.auth_header, api_key=data.api_key,
        enabled=data.enabled, allowed_tools=data.allowed_tools, rejected_tools=data.rejected_tools,
    )
    return _mcp_server_read(updated)


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    server = await _get_owned_mcp_server(db, current_user_id, server_id)
    await mcp_server_service.delete_mcp_server(db, server)


@router.post("/mcp-servers/{server_id}/test", response_model=McpServerTestResult)
async def test_mcp_server(
    server_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> McpServerTestResult:
    server = await _get_owned_mcp_server(db, current_user_id, server_id)
    result = await mcp_server_service.test_connection(server, extra_rejected=rd_agent.EXCLUDED_MCP_TOOLS)
    await mcp_server_service.record_connection_test(
        db, server, status=result["status"], discovered_tools=result["tools"],
    )
    return McpServerTestResult(status=result["status"], tools=result["tools"])


# ---------------------------------------------------------------------------
# Runs / traces
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=List[AgentRunSummary])
async def list_runs(
    agent_key: Optional[str] = Query(None),
    run_status: Optional[RunStatus] = Query(None, alias="status"),
    run_type: Optional[RunType] = Query(None),
    top_level: bool = Query(default=False, description="Exclude negotiation sub-runs (parent_run_id set)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[AgentRunSummary]:
    runs = await run_query_service.list_runs(
        db, current_user_id, agent_key=agent_key, status=run_status, run_type=run_type,
        top_level=top_level, limit=limit, offset=offset,
    )
    return [AgentRunSummary.model_validate(r) for r in runs]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
async def get_run(
    run_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AgentRunDetail:
    run = await run_query_service.get_run(db, current_user_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    events = await run_query_service.list_run_events(db, run_id)
    sub_runs = await run_query_service.list_sub_runs(db, current_user_id, run_id)
    return AgentRunDetail(
        **AgentRunSummary.model_validate(run).model_dump(),
        events=[AgentRunEventRead.model_validate(e) for e in events],
        sub_runs=[AgentRunSummary.model_validate(r) for r in sub_runs],
    )


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------

@router.get("/graph/entities", response_model=List[EntitySummary])
async def list_entities(
    response: Response,
    entity_type: Optional[EntityType] = Query(None),
    search: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[EntitySummary]:
    entities = await store.list_entities(
        db, current_user_id, entity_type=entity_type, search=search, min_confidence=min_confidence,
        limit=limit, offset=offset,
    )
    # X-Total-Count (not a body field) so response_model stays a bare list —
    # matches this repo's other list endpoints, none of which wrap results
    # in an envelope object.
    total = await store.count_entities(
        db, current_user_id, entity_type=entity_type, search=search, min_confidence=min_confidence,
    )
    response.headers["X-Total-Count"] = str(total)
    return [EntitySummary.model_validate(e) for e in entities]


@router.get("/graph/entities/{entity_id}", response_model=EntityDetail)
async def get_entity(
    entity_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> EntityDetail:
    entity = await store.get_entity(db, current_user_id, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    claims = await store.list_claims(db, current_user_id, entity_id)
    links = await store.list_links_for_entity(db, current_user_id, entity_id)
    return EntityDetail(
        **EntitySummary.model_validate(entity).model_dump(),
        aliases=entity.aliases, attributes=entity.attributes,
        claims=[ClaimRead.model_validate(c) for c in claims],
        links=[EntityLinkRead.model_validate(link) for link in links],
    )


@router.get("/graph/links", response_model=List[EntityLinkRead])
async def list_links(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[EntityLinkRead]:
    """Every link for the user — the graph view draws an edge for any link whose
    two endpoints are both in the entity set it already loaded from GET /graph/entities."""
    links = await store.list_links_for_user(db, current_user_id)
    return [EntityLinkRead.model_validate(link) for link in links]


@router.get("/graph/claims", response_model=List[ClaimRead])
async def list_claims(
    source: Optional[str] = Query(None),
    claim_status: Optional[ClaimStatus] = Query(None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[ClaimRead]:
    """Every claim for the user, optionally scoped to one source (== agent_key
    for every domain agent) — unlike GET /graph/entities/{id}, not scoped to
    a single entity. Backs a per-agent "what has it claimed" view."""
    claims = await store.list_claims_for_user(
        db, current_user_id, source=source, status=claim_status, limit=limit, offset=offset,
    )
    return [ClaimRead.model_validate(c) for c in claims]


@router.get("/graph/questions", response_model=List[PendingQuestionRead])
async def list_questions(
    response: Response,
    question_status: Optional[QuestionStatus] = Query(None, alias="status"),
    target: Optional[QuestionTarget] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[PendingQuestionRead]:
    questions = await store.list_questions(
        db, current_user_id, status=question_status, target=target, limit=limit, offset=offset,
    )
    # X-Total-Count so the UI can page through every open question instead of
    # silently truncating at `limit` — same pattern as GET /graph/entities.
    total = await store.count_questions(db, current_user_id, status=question_status, target=target)
    response.headers["X-Total-Count"] = str(total)

    # Resolve context.entity_id/candidate_entity_id to names in one batch query
    # instead of the UI showing raw UUIDs or fetching per-row.
    entity_ids = set()
    for q in questions:
        for key in ("entity_id", "candidate_entity_id"):
            raw = q.context.get(key)
            if raw:
                try:
                    entity_ids.add(uuid.UUID(raw))
                except (ValueError, TypeError):
                    continue
    entities = await store.list_entities_by_ids(db, current_user_id, list(entity_ids))
    name_by_id: Dict[str, str] = {str(e.id): e.canonical_name for e in entities}

    def _name_for(q: Any, key: str) -> Optional[str]:
        raw = q.context.get(key)
        return name_by_id.get(raw) if isinstance(raw, str) else None

    return [
        PendingQuestionRead.model_validate(q).model_copy(update={
            "entity_name": _name_for(q, "entity_id"),
            "candidate_entity_name": _name_for(q, "candidate_entity_id"),
        })
        for q in questions
    ]


@router.post("/graph/questions/{question_id}/answer", response_model=PendingQuestionRead)
async def answer_question(
    question_id: uuid.UUID,
    data: AnswerQuestionRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PendingQuestionRead:
    # Checked up front (not just via apply_question_answer's own "error" key)
    # so not-found and already-resolved map to distinct status codes instead
    # of both collapsing to 404.
    existing = await store.get_question(db, current_user_id, question_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    if existing.status != QuestionStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Question is already {existing.status.value}",
        )

    # Shared with the orchestrator's confirm_pending_answer chat tool
    # (strands_tools.py) — a same_as-shaped question actually links the two
    # entities when confirmed, not just a text note on the question.
    result = await reconciliation.apply_question_answer(
        db, current_user_id, question_id, data.answer_text, data.confirmed,
    )
    if "error" in result:
        # Not-found/already-resolved are already handled above — anything
        # else here is a genuine write failure (e.g. a context-referenced
        # entity no longer exists), not a 404.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    question = await store.get_question(db, current_user_id, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return PendingQuestionRead.model_validate(question)


@router.post("/graph/questions/{question_id}/dismiss", response_model=PendingQuestionRead)
async def dismiss_question(
    question_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PendingQuestionRead:
    question = await store.resolve_question(
        db, current_user_id, question_id, resolved_by=ResolvedBy.HUMAN, status=QuestionStatus.DISMISSED,
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return PendingQuestionRead.model_validate(question)
