"""I+D platform domain agent (Phase 6) — reads live from the R&D platform's
own MCP server instead of the documents table.

See specs/plan-multi-agent-knowledge.md. Unlike the other domain agents
(domain_agent.py), this source isn't ingested by a connector into the
documents table — there's no Document row, no get_unprocessed_documents,
no watermark. Each run queries the MCP server fresh and relies on
find_or_create_entity's existing same-user/type/name dedup to avoid
re-deriving duplicate entities from data it already saw. Acceptable for the
MVP; revisit if re-querying the whole platform every run proves too
expensive once real usage data exists.

MCP connection details (URL, bearer token) live only in Settings
(id_brain_mcp_url / id_brain_mcp_api_key) — never hardcoded here, never
logged. create_tasks is the MCP server's only write tool (self-documented as
such by the server); this agent is read-only, so create_tasks is excluded
via tool_filters AND re-asserted absent after loading, so a server-side
change to the tool catalog can't silently grant this agent write access.
"""
import asyncio
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent_run import RunStatus, RunTrigger, RunType
from app.models.mcp_server import McpServer
from app.services import mcp_server_service
from app.services.agent import agent_config_service, tracing
from app.services.agent.agent_config_service import EffectiveAgentConfig
from app.services.agent.knowledge.domain_agent import make_resolution_ladder_tools

logger = logging.getLogger(__name__)

SOURCE = "rd"
EXCLUDED_MCP_TOOLS: List[str] = ["create_tasks"]

RD_AGENT_SYSTEM_PROMPT = """\
Sos un agente de dominio del sistema de conocimiento unificado, responsable de \
la plataforma de I+D (equipo, iniciativas, proyectos, tareas, OKRs, \
publicaciones, novedades, capacitaciones, reuniones comerciales, plan mensual).

Tenés acceso directo a las tools de esa plataforma (list_initiatives, \
get_initiative, list_tasks, get_task_activity_summary, list_projects, \
list_publications, list_news, list_okrs, list_team, list_commercial_meetings, \
list_trainings, get_monthly_plan, search_knowledge). Usalas para explorar el \
estado actual — no tenés una cola de documentos no leídos, así que cada corrida \
volvés a mirar el estado vigente.

Tu mandato:
1. Explorá el equipo, las iniciativas y los proyectos activos con las tools \
disponibles.
2. Por cada persona, iniciativa, proyecto o tema relevante, identificá si ya \
existe en la base de conocimiento con find_or_create_entity antes de crear \
una entidad nueva.
3. Guardá cada afirmación relevante con add_claim, citando tu confianza real \
(0-1) y, cuando corresponda, source_ref (ej. el id de la iniciativa o tarea).
4. Sos de solo lectura hacia la plataforma de I+D: nunca existe una tool para \
crear o modificar tareas ahí — si no la ves entre tus tools, es intencional, \
no la busques ni la simules.

Escalera de resolución de dudas — nunca le preguntes al humano directo:
1. Si algo no te cierra, primero consultá el conocimiento existente con \
consult_knowledge_base.
2. Si sigue sin resolverse, consultá a tus pares con ask_peer_agents.
3. Si ninguno de los dos resuelve la duda, usá escalate_or_validate. Si llegaste a \
una respuesta parcial en los pasos 1-2, pasala como candidate_answer para que el \
humano la valide en vez de responder una pregunta en blanco.

Priorizá la solidez del conocimiento por sobre la velocidad: mejor un claim con \
confianza baja y correctamente marcada como tal, que inventar certeza."""


async def _resolve_mcp_server(
    db: AsyncSession, user_id: uuid.UUID, config: EffectiveAgentConfig,
) -> Optional[McpServer]:
    """The user-administered McpServer this run should use, if any.

    Only the first id in config.mcp_server_ids is honored — rd_agent (like
    every domain agent) runs one MCPClient connection per invocation; the
    plan's Phase 3 design deliberately doesn't extend the tool-loading loop
    to merge tools across multiple simultaneous MCP connections, since
    nothing today needs more than one MCP source per agent. A stale/deleted
    id (get_mcp_servers_by_ids finds nothing) falls through to the env-var
    bootstrap, same as an empty list.
    """
    if not config.mcp_server_ids:
        return None
    servers = await mcp_server_service.get_mcp_servers_by_ids(db, user_id, config.mcp_server_ids[:1])
    server = servers[0] if servers else None
    if server is not None and not server.enabled:
        logger.info("_resolve_mcp_server: mcp_server=%s is disabled, falling back to env config", server.id)
        return None
    return server


def _build_mcp_client(server: Optional[McpServer] = None) -> Any:
    """Construct (but don't start) the MCP client, with create_tasks rejected
    at the transport layer via tool_filters regardless of source.

    server: a user-registered McpServer (Phase 3) — its url/auth_header/api_key
    and allowed_tools/rejected_tools are used, with EXCLUDED_MCP_TOOLS always
    added to rejected (see mcp_server_service.build_tool_filters). None (the
    default — no server configured, or a stale mcp_server_ids reference) falls
    back to the id_brain_mcp_url/id_brain_mcp_api_key env vars exactly as
    before Phase 3 existed.
    """
    from strands.tools.mcp import MCPClient
    from strands.tools.mcp.mcp_client import ToolFilters

    if server is not None:
        api_key = mcp_server_service.get_decrypted_api_key(server)
        headers = {server.auth_header: f"Bearer {api_key}"} if api_key else {}
        tool_filters: ToolFilters = mcp_server_service.build_tool_filters(
            server, extra_rejected=EXCLUDED_MCP_TOOLS,
        )
        return MCPClient(url=server.url, headers=headers, tool_filters=tool_filters)

    settings = get_settings()
    tool_filters = {"rejected": list(EXCLUDED_MCP_TOOLS)}
    return MCPClient(
        url=settings.id_brain_mcp_url,
        headers={"Authorization": f"Bearer {settings.id_brain_mcp_api_key}"},
        tool_filters=tool_filters,
    )


async def run_rd_domain_agent(
    db: AsyncSession,
    user_id: uuid.UUID,
    embedder: Optional[Any] = None,
    trigger: RunTrigger = RunTrigger.MANUAL,
) -> Dict[str, Any]:
    """Entry point for the sync scheduler (or a manual trigger): one pass over
    the I+D platform's current state via its MCP server.

    A no-op (with a clear summary) if there's no MCP server to talk to — no
    user-registered McpServer referenced by AgentConfig.mcp_server_ids, AND
    id_brain_mcp_url isn't set — same "opt-in, disabled unless configured"
    pattern as web_search/http_request (strands_tools.py). No AgentRun is
    persisted for the no-op case — there's no agent invocation to trace, just
    a config check.
    """
    config = await agent_config_service.get_effective_config(
        db, user_id, SOURCE, default_system_prompt=RD_AGENT_SYSTEM_PROMPT,
    )
    if not config.enabled:
        logger.info("run_rd_domain_agent: user=%s disabled via agent config, skipping", user_id)
        return {"source": SOURCE, "summary": "skipped: disabled via agent config"}

    settings = get_settings()
    server = await _resolve_mcp_server(db, user_id, config)
    if server is None and not settings.id_brain_mcp_url:
        logger.info("run_rd_domain_agent: no mcp_server configured and id_brain_mcp_url unset, skipping")
        return {"source": SOURCE, "summary": "skipped: id_brain_mcp_url not configured"}

    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    from app.services.agent.strands_model import build_openai_model

    run_id = await tracing.start_run(
        user_id, agent_key=SOURCE, run_type=RunType.RD_AGENT, trigger=trigger,
        model_id=config.model_id or settings.llm_model,
    )
    agent: Any = None
    mcp_client: Any = None
    try:
        # _build_mcp_client(server) itself can raise (e.g. ValueError on a
        # malformed url from a user-registered McpServer row) — building it
        # inside this try is what lets the except/finally below still close
        # out the AgentRun instead of leaving it stuck at RUNNING forever.
        mcp_client = _build_mcp_client(server)
        mcp_client.start()
        mcp_tools = mcp_client.list_tools_sync()
        loaded_names = {t.tool_name for t in mcp_tools}
        leaked = loaded_names & set(EXCLUDED_MCP_TOOLS)
        if leaked:
            raise RuntimeError(f"MCP write tool(s) leaked past tool_filters: {leaked}")

        # MCP tools (the source's actual data-access layer) are never
        # enabled_tools-filtered — only the shared resolution ladder is
        # configurable here, same scoping as make_domain_agent.
        ladder_tools = agent_config_service.filter_tools(
            make_resolution_ladder_tools(
                SOURCE, db, user_id, embedder=embedder, run_id=run_id, trigger=trigger,
            ),
            config.enabled_tools,
        )
        tools = [*mcp_tools, *ladder_tools]
        model = build_openai_model(model=config.model_id)
        agent = Agent(
            model=model, tools=tools, system_prompt=config.system_prompt,
            name=f"{SOURCE}_domain_agent", tool_executor=SequentialToolExecutor(),
        )
        task = (
            "Explorá el estado actual de la plataforma de I+D (equipo, iniciativas, "
            "proyectos, tareas, OKRs) y actualizá la base de conocimiento compartida "
            "siguiendo tu mandato."
        )
        result = await agent.invoke_async(task)
    except asyncio.CancelledError:
        if agent is not None:
            await tracing.record_agent_events(run_id, agent, actor=f"{SOURCE}_domain_agent")
        await tracing.finish_run(run_id, RunStatus.FAILED, error="cancelled")
        raise
    except Exception as e:
        if agent is not None:
            await tracing.record_agent_events(run_id, agent, actor=f"{SOURCE}_domain_agent")
        await tracing.finish_run(run_id, RunStatus.FAILED, error=str(e))
        raise
    finally:
        if mcp_client is not None:
            mcp_client.stop(*sys.exc_info())

    await tracing.record_agent_events(run_id, agent, actor=f"{SOURCE}_domain_agent")
    await tracing.finish_run(
        run_id, RunStatus.COMPLETED, summary=str(result), usage_source=agent,
    )
    logger.info("run_rd_domain_agent: user=%s done", user_id)
    return {"source": SOURCE, "summary": str(result)}
