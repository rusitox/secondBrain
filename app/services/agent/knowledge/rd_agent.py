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
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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


def _build_mcp_client() -> Any:
    """Construct (but don't start) the MCP client, with create_tasks rejected
    at the transport layer via tool_filters."""
    from strands.tools.mcp import MCPClient
    from strands.tools.mcp.mcp_client import ToolFilters

    settings = get_settings()
    tool_filters: ToolFilters = {"rejected": list(EXCLUDED_MCP_TOOLS)}
    return MCPClient(
        url=settings.id_brain_mcp_url,
        headers={"Authorization": f"Bearer {settings.id_brain_mcp_api_key}"},
        tool_filters=tool_filters,
    )


async def run_rd_domain_agent(
    db: AsyncSession,
    user_id: uuid.UUID,
    embedder: Optional[Any] = None,
) -> Dict[str, Any]:
    """Entry point for the sync scheduler (or a manual trigger): one pass over
    the I+D platform's current state via its MCP server.

    A no-op (with a clear summary) if id_brain_mcp_url isn't configured —
    same "opt-in, disabled unless configured" pattern as web_search/
    http_request (strands_tools.py).
    """
    settings = get_settings()
    if not settings.id_brain_mcp_url:
        logger.info("run_rd_domain_agent: id_brain_mcp_url not configured, skipping")
        return {"source": SOURCE, "summary": "skipped: id_brain_mcp_url not configured"}

    from strands import Agent
    from strands.tools.executors import SequentialToolExecutor

    from app.services.agent.strands_model import build_openai_model

    mcp_client = _build_mcp_client()
    mcp_client.start()
    try:
        mcp_tools = mcp_client.list_tools_sync()
        loaded_names = {t.tool_name for t in mcp_tools}
        leaked = loaded_names & set(EXCLUDED_MCP_TOOLS)
        assert not leaked, f"MCP write tool(s) leaked past tool_filters: {leaked}"

        tools = [
            *mcp_tools,
            *make_resolution_ladder_tools(SOURCE, db, user_id, embedder=embedder),
        ]
        model = build_openai_model()
        agent = Agent(
            model=model, tools=tools, system_prompt=RD_AGENT_SYSTEM_PROMPT,
            name=f"{SOURCE}_domain_agent", tool_executor=SequentialToolExecutor(),
        )
        task = (
            "Explorá el estado actual de la plataforma de I+D (equipo, iniciativas, "
            "proyectos, tareas, OKRs) y actualizá la base de conocimiento compartida "
            "siguiendo tu mandato."
        )
        result = await agent.invoke_async(task)
    finally:
        mcp_client.stop(*sys.exc_info())

    logger.info("run_rd_domain_agent: user=%s done", user_id)
    return {"source": SOURCE, "summary": str(result)}
