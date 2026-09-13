"""Resolves the effective configuration for one agent: code defaults merged
with a user's AgentConfig override, if any.

specs/plan-knowledge-backoffice.md, Phase 2. The core guarantee: a user with no
AgentConfig row for an agent_key gets *exactly* today's hardcoded behavior —
every field on EffectiveAgentConfig falls back to the caller-supplied default
when the row is absent, or when the row exists but leaves that field NULL
(NULL means "use the code default", not "use an empty value" — see
app/models/agent_config.py). That's what makes introducing this table safe to
ship without a backfill: nothing changes for a user until they explicitly save
an override via the backoffice.
"""
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import AgentConfig
from app.models.integration import Platform

logger = logging.getLogger(__name__)

# Every agent_key the backoffice can configure. Mirrors
# domain_agent.REGISTERED_SOURCES + "orchestrator" without importing
# domain_agent — domain_agent already imports this module, so importing it
# back here would be circular. Derived from Platform (not hardcoded
# per-source strings) so a new connector's Platform member automatically
# becomes configurable, same rationale domain_agent.py's own comment gives
# for building REGISTERED_SOURCES this way.
KNOWN_AGENT_KEYS: List[str] = [p.value for p in Platform] + ["rd", "orchestrator"]

UNSET: Any = object()
"""Sentinel distinguishing "field not mentioned" from "field explicitly set
to None" in upsert_agent_config — see that function's docstring. Exported
(not a leading-underscore name) because API callers (app/api/routers/
backoffice.py) need to pass it as a default when a field was absent from a
PATCH-style request body."""


@dataclass
class EffectiveAgentConfig:
    enabled: bool
    model_id: Optional[str]
    system_prompt: str
    enabled_tools: Optional[List[str]]
    mcp_server_ids: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)


async def get_effective_config(
    db: AsyncSession, user_id: uuid.UUID, agent_key: str, default_system_prompt: str,
) -> EffectiveAgentConfig:
    """Read-only merge of the AgentConfig row (if any) over code defaults.

    default_system_prompt is supplied by the caller rather than looked up here
    because it's often source-specific (e.g. domain_agent's per-source
    DOMAIN_AGENT_SYSTEM_PROMPT.format(...)) — this function doesn't know how
    to build it, only when to use it (row absent, or row.system_prompt NULL).

    Fetches the row itself — a caller that also needs the raw row (e.g. the
    backoffice API's has_override flag) should call get_config_row() once and
    pass it to effective_config_from_row() instead of calling both this
    function and get_config_row() separately, which would query twice.
    """
    row = await get_config_row(db, user_id, agent_key)
    return effective_config_from_row(row, default_system_prompt)


def effective_config_from_row(
    row: Optional[AgentConfig], default_system_prompt: str,
) -> EffectiveAgentConfig:
    """Same merge get_effective_config does, from an already-fetched row (or
    None) — split out so a caller that needs both the row and the effective
    config doesn't have to fetch the row twice."""
    if row is None:
        return EffectiveAgentConfig(
            enabled=True, model_id=None, system_prompt=default_system_prompt, enabled_tools=None,
        )
    return EffectiveAgentConfig(
        enabled=row.enabled,
        model_id=row.model_id or None,
        system_prompt=row.system_prompt or default_system_prompt,
        enabled_tools=row.enabled_tools,
        mcp_server_ids=list(row.mcp_server_ids or []),
        params=dict(row.params or {}),
    )


async def get_config_row(
    db: AsyncSession, user_id: uuid.UUID, agent_key: str,
) -> Optional[AgentConfig]:
    """The raw override row, if any — None means "no override", distinct
    from a row that exists but leaves every field NULL. The backoffice API
    uses this (via has_override in AgentConfigRead) to show a user whether
    they're seeing code defaults or their own saved override."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.user_id == user_id, AgentConfig.agent_key == agent_key)
    )
    return result.scalar_one_or_none()


async def upsert_agent_config(
    db: AsyncSession,
    user_id: uuid.UUID,
    agent_key: str,
    enabled: Optional[bool] = None,
    model_id: Optional[str] = UNSET,
    system_prompt: Optional[str] = UNSET,
    enabled_tools: Optional[List[str]] = UNSET,
    mcp_server_ids: Optional[List[str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> AgentConfig:
    """Create-or-update the override row, touching only the fields the
    caller actually passed. model_id/system_prompt/enabled_tools default to
    the UNSET sentinel (not None) because None is itself a meaningful value
    here — "clear this override back to the code default" — indistinguishable
    from "the caller didn't mention this field" if both used the same
    default. mcp_server_ids/params don't need the sentinel: their "cleared"
    state ([]/{}) and their "not mentioned" state are the same no-op either way.
    """
    row = await get_config_row(db, user_id, agent_key)
    if row is None:
        row = AgentConfig(user_id=user_id, agent_key=agent_key)
        db.add(row)
    if enabled is not None:
        row.enabled = enabled
    if model_id is not UNSET:
        row.model_id = model_id
    if system_prompt is not UNSET:
        row.system_prompt = system_prompt
    if enabled_tools is not UNSET:
        row.enabled_tools = enabled_tools
    if mcp_server_ids is not None:
        row.mcp_server_ids = mcp_server_ids
    if params is not None:
        row.params = params
    await db.flush()
    await db.refresh(row)
    return row


async def delete_agent_config(db: AsyncSession, row: AgentConfig) -> None:
    """Revert an agent to code defaults by deleting its override row entirely."""
    await db.delete(row)
    await db.flush()


def filter_tools(tools: List[Any], enabled_tools: Optional[List[str]]) -> List[Any]:
    """Keep only tools named in enabled_tools; None (the default — no config
    row, or a row that never touched this field) means keep everything.

    A name in enabled_tools that matches nothing (typo, renamed tool) is
    silently dropped rather than erroring — the agent still runs, just with
    fewer tools than its system prompt expects. Logged as a warning so a
    misconfigured enabled_tools list is diagnosable from logs instead of only
    showing up as unexplained degraded behavior.
    """
    if enabled_tools is None:
        return tools
    allowed = set(enabled_tools)
    present = {_tool_name(t) for t in tools}
    unmatched = allowed - present
    if unmatched:
        logger.warning(
            "filter_tools: enabled_tools contains name(s) with no matching tool: %s (available: %s)",
            sorted(unmatched), sorted(n for n in present if n),
        )
    return [t for t in tools if _tool_name(t) in allowed]


def _tool_name(t: Any) -> Optional[str]:
    return getattr(t, "tool_name", None) or getattr(t, "__name__", None)
