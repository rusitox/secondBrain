"""Declarative catalog of the tools each agent type can be given.

Backs the knowledge-backoffice's tool listing (specs/plan-knowledge-backoffice.md)
and app.services.agent.agent_config_service.filter_tools, which cross-references a
user's AgentConfig.enabled_tools against actual tool names. This module only
*describes* tools defined elsewhere (strands_tools.make_agent_tools,
domain_agent.make_resolution_ladder_tools) — every `name` here must match that
tool's real Strands `.tool_name` exactly, which test_tool_registry.py checks by
building the real tool lists and diffing names against this catalog rather than
hardcoding a second copy of them.

Two tool groups are deliberately left out of "configurable" (never affected by
enabled_tools even though they're real tools an agent has):
- get_unprocessed_documents / mark_document_processed: document-backed domain
  agents' own watermarking. Disabling them doesn't reduce agent capability, it
  breaks the mandate (an agent that can't mark documents processed re-reads the
  same batch forever) — not a judgment call a config checkbox should make.
- A domain agent's MCP-sourced tools (e.g. rd's I+D platform tools): those are
  the source's actual data-access layer, registered dynamically per MCP server
  (Phase 3), not part of this static catalog.
"""
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    category: str


# The five tools every domain agent (document-backed or MCP-backed) shares via
# domain_agent.make_resolution_ladder_tools — the only tools Phase 2's
# enabled_tools config actually gates for domain/rd agents.
RESOLUTION_LADDER_TOOLS: List[ToolInfo] = [
    ToolInfo(
        "find_or_create_entity", "Find an existing entity by name/alias, or create a new one.",
        "resolution_ladder",
    ),
    ToolInfo(
        "add_claim", "Record what a document asserts about an entity, with confidence and provenance.",
        "resolution_ladder",
    ),
    ToolInfo(
        "consult_knowledge_base", "Search existing entities/claims — step 1 of the resolution ladder.",
        "resolution_ladder",
    ),
    ToolInfo(
        "ask_peer_agents", "Negotiate a doubt with peer domain agents via a scoped Swarm — step 2.",
        "resolution_ladder",
    ),
    ToolInfo(
        "escalate_or_validate", "Raise a question to the human, carrying any partial answer — step 3/4.",
        "resolution_ladder",
    ),
]

# strands_tools.make_agent_tools — the chat orchestrator's tool set. web_search
# and http_request are themselves opt-in at the settings level (only registered
# when brave_search_api_key / http_request_allowed_domains is configured) —
# listed here regardless since enabled_tools only filters what's *offered*,
# never grants a tool settings didn't already register.
ORCHESTRATOR_TOOLS: List[ToolInfo] = [
    ToolInfo("search_memory", "Semantic search across ingested documents.", "orchestrator"),
    ToolInfo("list_tasks", "List the user's open commitments/tasks.", "orchestrator"),
    ToolInfo("get_calendar", "Read upcoming calendar events.", "orchestrator"),
    ToolInfo("get_user_style", "Fetch the user's communication style/persona profile.", "orchestrator"),
    ToolInfo("search_learnings", "Search previously saved learnings.", "orchestrator"),
    ToolInfo("save_learning", "Save a new learning for future recall.", "orchestrator"),
    ToolInfo("get_sync_status", "Check the status of connector sync integrations.", "orchestrator"),
    ToolInfo("get_current_datetime", "Get the current date/time in the user's timezone.", "orchestrator"),
    ToolInfo("query_knowledge", "Query the multi-agent knowledge graph's consolidated view.", "orchestrator"),
    ToolInfo("get_pending_questions", "List questions domain agents escalated to the human.", "orchestrator"),
    ToolInfo("confirm_pending_answer", "Answer/confirm a pending question, closing the resolution loop.", "orchestrator"),
    ToolInfo("web_search", "Brave web search (opt-in via brave_search_api_key).", "orchestrator"),
    ToolInfo("http_request", "Fetch a URL from an allowed domain (opt-in).", "orchestrator"),
]

DOCUMENT_WATERMARK_TOOLS: List[ToolInfo] = [
    ToolInfo("get_unprocessed_documents", "Read this source's unprocessed documents.", "watermark"),
    ToolInfo("mark_document_processed", "Mark a document processed so it isn't re-read.", "watermark"),
]

_DOCUMENT_BACKED_SOURCES = {"slack", "outlook", "teams", "fathom", "notion"}


def tools_for_agent(agent_key: str) -> List[ToolInfo]:
    """All tools a given agent_key can have — configurable and unconfigurable
    alike. See module docstring for which ones enabled_tools actually gates."""
    if agent_key == "orchestrator":
        return list(ORCHESTRATOR_TOOLS)
    if agent_key == "rd":
        return list(RESOLUTION_LADDER_TOOLS)
    if agent_key in _DOCUMENT_BACKED_SOURCES:
        return [*DOCUMENT_WATERMARK_TOOLS, *RESOLUTION_LADDER_TOOLS]
    return []


def configurable_tools_for_agent(agent_key: str) -> List[ToolInfo]:
    """Subset of tools_for_agent that enabled_tools is actually allowed to
    gate — excludes watermark tools and (for orchestrator) nothing, since every
    orchestrator tool is a genuine optional capability."""
    if agent_key == "orchestrator":
        return list(ORCHESTRATOR_TOOLS)
    if agent_key in {"rd", *_DOCUMENT_BACKED_SOURCES}:
        return list(RESOLUTION_LADDER_TOOLS)
    return []


def all_tools_by_name() -> Dict[str, ToolInfo]:
    seen: Dict[str, ToolInfo] = {}
    for group in (RESOLUTION_LADDER_TOOLS, ORCHESTRATOR_TOOLS, DOCUMENT_WATERMARK_TOOLS):
        for t in group:
            seen[t.name] = t
    return seen
