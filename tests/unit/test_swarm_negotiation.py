"""Unit tests for the shared scoped-Swarm negotiation core.

Used by both domain_agent._ask_peer_agents (proactive) and
reconciliation.negotiate_same_as (reactive) — see swarm_negotiation.py's
module docstring for why this exists as one shared function instead of two
copies of the same Agent/Swarm scaffold.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agent.knowledge.swarm_negotiation import run_negotiation


class TestRunNegotiation:
    async def test_builds_one_agent_per_node_spec_and_invokes_swarm(self) -> None:
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        node_specs = [
            {"name": "a_negotiator", "system_prompt": "sos a", "tools": []},
            {"name": "b_negotiator", "system_prompt": "sos b", "tools": []},
        ]

        with patch("strands.Agent") as mock_agent_cls, \
             patch("strands.multiagent.Swarm") as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            mock_swarm_cls.return_value.invoke_async = AsyncMock(return_value=MagicMock())
            await run_negotiation(node_specs, "¿son la misma entidad?", log_context="test")

        assert mock_agent_cls.call_count == 2
        names = {call.kwargs["name"] for call in mock_agent_cls.call_args_list}
        assert names == {"a_negotiator", "b_negotiator"}
        mock_swarm_cls.assert_called_once()
        mock_swarm_cls.return_value.invoke_async.assert_awaited_once_with("¿son la misma entidad?")

    async def test_swarm_exception_is_caught_and_logged_not_raised(self) -> None:
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"
        node_specs = [{"name": "a_negotiator", "system_prompt": "sos a", "tools": []}]

        with patch("strands.Agent", return_value=MagicMock()), \
             patch("strands.multiagent.Swarm") as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            mock_swarm_cls.return_value.invoke_async = AsyncMock(side_effect=RuntimeError("boom"))
            await run_negotiation(node_specs, "¿duda?", log_context="test")  # must not raise
