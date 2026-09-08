"""Schemas for the knowledge-system backoffice API (specs/plan-knowledge-backoffice.md,
Phase 4): agent config, MCP servers, agent runs/traces, and the knowledge graph.
"""
import ipaddress
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

from app.models.agent_run import RunStatus, RunTrigger, RunType
from app.models.agent_run_event import RunEventType
from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionStatus, QuestionTarget, ResolvedBy

_BLOCKED_MCP_HOSTS = {"localhost", "metadata.google.internal"}


def _validate_mcp_url(url: str) -> str:
    """Reject the obvious SSRF targets for a user-supplied MCP server URL:
    non-http(s) schemes, missing host, and IP-literal loopback/private/
    link-local/reserved ranges (this blocks http://169.254.169.254/... —
    the cloud-metadata endpoint — among others).

    This is a literal-value check only — it does NOT resolve hostnames, so a
    DNS name that currently points at a public IP but gets rebound to an
    internal one after this check passes (classic TOCTOU/DNS-rebinding SSRF)
    is not covered. Closing that gap needs enforcement at the HTTP
    connection layer (e.g. validating the resolved IP right before connect
    in mcp_server_service.test_connection/rd_agent's MCPClient), not here —
    out of scope for this pass, but worth flagging before this endpoint is
    treated as fully SSRF-hardened.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise ValueError("url must include a host")
    host_lower = host.lower()
    if (
        host_lower in _BLOCKED_MCP_HOSTS
        or host_lower.endswith(".internal")
        or host_lower.endswith(".local")
    ):
        raise ValueError(f"url host {host!r} is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    ):
        raise ValueError(f"url host {host!r} resolves to a disallowed IP range")
    return url


# ---------------------------------------------------------------------------
# Agent config
# ---------------------------------------------------------------------------

class AgentConfigRead(BaseModel):
    agent_key: str
    enabled: bool
    model_id: Optional[str]
    system_prompt: str
    enabled_tools: Optional[List[str]]
    mcp_server_ids: List[str]
    params: Dict[str, Any]
    has_override: bool


class AgentConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    model_id: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled_tools: Optional[List[str]] = None
    mcp_server_ids: Optional[List[str]] = None
    params: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------

class ToolInfoRead(BaseModel):
    name: str
    description: str
    category: str
    configurable: bool


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

class McpServerCreate(BaseModel):
    name: str
    url: str
    auth_header: str = "Authorization"
    api_key: Optional[str] = None
    enabled: bool = True
    allowed_tools: Optional[List[str]] = None
    rejected_tools: Optional[List[str]] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_mcp_url(v)


class McpServerUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    auth_header: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None
    allowed_tools: Optional[List[str]] = None
    rejected_tools: Optional[List[str]] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_mcp_url(v) if v is not None else v


class McpServerRead(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    auth_header: str
    enabled: bool
    allowed_tools: Optional[List[str]]
    rejected_tools: Optional[List[str]]
    last_checked_at: Optional[datetime]
    last_status: Optional[str]
    discovered_tools: List[Dict[str, Any]]
    has_api_key: bool
    created_at: datetime
    updated_at: datetime
    # Deliberately no api_key/api_key_encrypted field — never returned,
    # same convention as IntegrationRead omitting access_token/refresh_token.


class McpServerTestResult(BaseModel):
    status: str
    tools: List[Dict[str, str]]


# ---------------------------------------------------------------------------
# Agent runs / traces
# ---------------------------------------------------------------------------

class AgentRunSummary(BaseModel):
    id: uuid.UUID
    agent_key: str
    run_type: RunType
    trigger: RunTrigger
    status: RunStatus
    model_id: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    total_tokens: Optional[int]
    summary: Optional[str]
    error: Optional[str]
    parent_run_id: Optional[uuid.UUID]
    stats: Dict[str, Any]
    """Already loaded on every AgentRun row (JSONB, default {}) — free to expose on
    the list endpoint too, no extra query. Negotiation runs carry {question,
    participants, ...} here (see tracing.finish_run call sites in domain_agent.py /
    reconciliation.py), which the backoffice UI's Conversations list reads without
    an N+1 fetch per row."""

    model_config = {"from_attributes": True}


class AgentRunEventRead(BaseModel):
    id: uuid.UUID
    seq: int
    event_type: RunEventType
    actor: Optional[str]
    tool_name: Optional[str]
    payload: Dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunDetail(AgentRunSummary):
    events: List[AgentRunEventRead]
    sub_runs: List[AgentRunSummary]


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------

class EntitySummary(BaseModel):
    id: uuid.UUID
    entity_type: EntityType
    canonical_name: str
    confidence: float

    model_config = {"from_attributes": True}


class ClaimRead(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID
    source: str
    source_ref: Optional[str]
    claim_text: str
    claim_type: Optional[str]
    confidence: float
    status: ClaimStatus
    asserted_by_agent: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EntityLinkRead(BaseModel):
    id: uuid.UUID
    entity_id_a: uuid.UUID
    entity_id_b: uuid.UUID
    relation_type: str
    confidence: float
    resolved_by: LinkResolvedBy

    model_config = {"from_attributes": True}


class EntityDetail(EntitySummary):
    aliases: List[str]
    attributes: Dict[str, Any]
    claims: List[ClaimRead]
    links: List[EntityLinkRead]


class PendingQuestionRead(BaseModel):
    id: uuid.UUID
    raised_by_agent: str
    question_text: str
    context: Dict[str, Any]
    target: QuestionTarget
    candidate_answer: Optional[str]
    candidate_confidence: Optional[float]
    status: QuestionStatus
    resolved_by: Optional[ResolvedBy]
    answer_text: Optional[str]
    answered_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class AnswerQuestionRequest(BaseModel):
    answer_text: str
