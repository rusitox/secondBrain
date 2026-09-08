"""Tests for app.services.agent.tool_registry — the declarative tool catalog
backing the backoffice's tool listing and enabled_tools filtering
(specs/plan-knowledge-backoffice.md, Phase 2).
"""
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent import tool_registry
from app.services.agent.knowledge.domain_agent import make_resolution_ladder_tools, make_watermark_tools
from app.services.agent.strands_tools import make_agent_tools


def _settings(brave_search_api_key: str = "bsk-test", http_request_allowed_domains: str = "docs.python.org") -> MagicMock:
    settings = MagicMock()
    settings.brave_search_api_key = brave_search_api_key
    settings.http_request_allowed_domains = http_request_allowed_domains
    return settings


class TestToolsForAgent:
    def test_document_backed_source_has_watermark_plus_ladder(self) -> None:
        names = {t.name for t in tool_registry.tools_for_agent("slack")}
        assert names == {
            "get_unprocessed_documents", "mark_document_processed",
            "find_or_create_entity", "add_claim", "consult_knowledge_base",
            "ask_peer_agents", "escalate_or_validate",
        }

    def test_all_five_document_sources_match(self) -> None:
        for source in ("slack", "outlook", "teams", "fathom", "notion"):
            names = {t.name for t in tool_registry.tools_for_agent(source)}
            assert "get_unprocessed_documents" in names
            assert "find_or_create_entity" in names

    def test_rd_has_only_ladder_tools(self) -> None:
        names = {t.name for t in tool_registry.tools_for_agent("rd")}
        assert names == {
            "find_or_create_entity", "add_claim", "consult_knowledge_base",
            "ask_peer_agents", "escalate_or_validate",
        }
        assert "get_unprocessed_documents" not in names

    def test_orchestrator_has_fourteen_tools(self) -> None:
        names = {t.name for t in tool_registry.tools_for_agent("orchestrator")}
        assert len(names) == 14
        assert "search_memory" in names
        assert "web_search" in names
        assert "ask_domain_agents" in names

    def test_unknown_agent_key_returns_empty(self) -> None:
        assert tool_registry.tools_for_agent("nonexistent") == []


class TestConfigurableToolsForAgent:
    def test_document_source_excludes_watermark_tools(self) -> None:
        names = {t.name for t in tool_registry.configurable_tools_for_agent("slack")}
        assert "get_unprocessed_documents" not in names
        assert "mark_document_processed" not in names
        assert "ask_peer_agents" in names

    def test_orchestrator_includes_every_tool(self) -> None:
        configurable = {t.name for t in tool_registry.configurable_tools_for_agent("orchestrator")}
        every = {t.name for t in tool_registry.tools_for_agent("orchestrator")}
        assert configurable == every


class TestAllToolsByName:
    def test_no_name_collisions_across_groups(self) -> None:
        by_name = tool_registry.all_tools_by_name()
        assert by_name["ask_peer_agents"].category == "resolution_ladder"
        assert by_name["search_memory"].category == "orchestrator"
        assert by_name["get_unprocessed_documents"].category == "watermark"


class TestRegistryMatchesRealTools:
    """The module docstring's promise: names here must match the real tools'
    .tool_name exactly, checked by building the real tool lists rather than
    hardcoding a second copy of them."""

    async def test_resolution_ladder_names_match_make_resolution_ladder_tools(
        self, db_session: AsyncSession,
    ) -> None:
        real_tools = make_resolution_ladder_tools("slack", db_session, uuid.uuid4())
        real_names = {t.tool_name for t in real_tools}
        registry_names = {t.name for t in tool_registry.RESOLUTION_LADDER_TOOLS}
        assert real_names == registry_names

    async def test_watermark_names_match_make_watermark_tools(self, db_session: AsyncSession) -> None:
        real_tools = make_watermark_tools("slack", db_session, uuid.uuid4())
        real_names = {t.tool_name for t in real_tools}
        registry_names = {t.name for t in tool_registry.DOCUMENT_WATERMARK_TOOLS}
        assert real_names == registry_names

    async def test_orchestrator_names_match_make_agent_tools(self, db_session: AsyncSession) -> None:
        with patch("app.core.config.get_settings", return_value=_settings()):
            real_tools = make_agent_tools(db=db_session, user_id=uuid.uuid4(), user_timezone="UTC")
        real_names = {getattr(t, "tool_name", None) for t in real_tools}
        registry_names = {t.name for t in tool_registry.ORCHESTRATOR_TOOLS}
        assert real_names == registry_names
