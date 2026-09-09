"""Tests for app.services.agent.agent_config_service — resolving an agent's
effective config (code defaults merged with an optional AgentConfig override).
specs/plan-knowledge-backoffice.md, Phase 2.
"""
import uuid
from typing import List

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import AgentConfig
from app.services.agent import agent_config_service
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


class _FakeTool:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name


class TestGetEffectiveConfigNoRow:
    async def test_no_row_reproduces_code_defaults(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cfg1@example.com")

        config = await agent_config_service.get_effective_config(
            db_session, user_id, "slack", default_system_prompt="default prompt",
        )

        assert config.enabled is True
        assert config.model_id is None
        assert config.system_prompt == "default prompt"
        assert config.enabled_tools is None
        assert config.mcp_server_ids == []
        assert config.params == {}


class TestGetEffectiveConfigWithRow:
    async def test_full_override_row(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cfg2@example.com")
        db_session.add(AgentConfig(
            user_id=user_id, agent_key="slack", enabled=False, model_id="openai/gpt-4o",
            system_prompt="custom prompt", enabled_tools=["add_claim"],
            mcp_server_ids=["mcp-1"], params={"batch_size": 5},
        ))
        await db_session.commit()

        config = await agent_config_service.get_effective_config(
            db_session, user_id, "slack", default_system_prompt="default prompt",
        )

        assert config.enabled is False
        assert config.model_id == "openai/gpt-4o"
        assert config.system_prompt == "custom prompt"
        assert config.enabled_tools == ["add_claim"]
        assert config.mcp_server_ids == ["mcp-1"]
        assert config.params == {"batch_size": 5}

    async def test_null_fields_on_row_fall_back_to_defaults(self, db_session: AsyncSession) -> None:
        """A row can exist (e.g. just to flip `enabled`) without touching
        every field — NULL model_id/system_prompt must still fall back to the
        code default, not to None/empty."""
        user_id = await _make_persisted_user(db_session, email="cfg3@example.com")
        db_session.add(AgentConfig(user_id=user_id, agent_key="slack", enabled=True))
        await db_session.commit()

        config = await agent_config_service.get_effective_config(
            db_session, user_id, "slack", default_system_prompt="default prompt",
        )

        assert config.enabled is True
        assert config.model_id is None
        assert config.system_prompt == "default prompt"
        assert config.enabled_tools is None

    async def test_scoped_by_user_and_agent_key(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="cfg4a@example.com")
        user_b = await _make_persisted_user(db_session, email="cfg4b@example.com")
        db_session.add(AgentConfig(user_id=user_a, agent_key="slack", model_id="openai/gpt-4o"))
        db_session.add(AgentConfig(user_id=user_a, agent_key="outlook", model_id="openai/gpt-4o-mini"))
        await db_session.commit()

        config_b = await agent_config_service.get_effective_config(
            db_session, user_b, "slack", default_system_prompt="default",
        )
        config_a_outlook = await agent_config_service.get_effective_config(
            db_session, user_a, "outlook", default_system_prompt="default",
        )

        assert config_b.model_id is None  # user_b has no row at all
        assert config_a_outlook.model_id == "openai/gpt-4o-mini"  # not user_a's slack row


class TestFilterTools:
    def test_none_keeps_everything(self) -> None:
        tools: List[_FakeTool] = [_FakeTool("a"), _FakeTool("b")]
        assert agent_config_service.filter_tools(tools, None) == tools

    def test_filters_to_allowed_names(self) -> None:
        tools = [_FakeTool("a"), _FakeTool("b"), _FakeTool("c")]
        result = agent_config_service.filter_tools(tools, ["a", "c"])
        assert [t.tool_name for t in result] == ["a", "c"]

    def test_empty_list_disables_all(self) -> None:
        tools = [_FakeTool("a"), _FakeTool("b")]
        assert agent_config_service.filter_tools(tools, []) == []

    def test_falls_back_to_dunder_name_when_no_tool_name_attr(self) -> None:
        def plain_function() -> None:
            pass

        result = agent_config_service.filter_tools([plain_function], ["plain_function"])
        assert result == [plain_function]
