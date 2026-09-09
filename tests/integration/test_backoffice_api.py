"""Integration tests for the knowledge-backoffice API (specs/plan-knowledge-backoffice.md,
Phase 4): agent config, tools, MCP servers, runs, and the knowledge graph.

LLM/MCP calls are always mocked — these tests never hit a real network.
"""
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import AgentConfig
from app.models.agent_run import AgentRun, RunStatus, RunTrigger, RunType
from app.models.agent_run_event import AgentRunEvent, RunEventType
from app.models.entity import EntityType
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionStatus, QuestionTarget
from app.services import mcp_server_service
from app.services.agent.knowledge import store
from tests.factories import make_user


async def _create_user(client: AsyncClient, email: str = "bo@example.com") -> str:
    resp = await client.post("/users/", json={"email": email, "full_name": "BO User"})
    return resp.json()["id"]


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class TestListAndGetAgents:
    async def test_list_returns_every_known_agent_with_defaults(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents1@example.com")
        resp = await client.get("/backoffice/agents", headers={"X-User-Id": user_id})
        assert resp.status_code == 200
        data = resp.json()
        keys = {a["agent_key"] for a in data}
        assert keys == {"slack", "outlook", "teams", "fathom", "notion", "rd", "orchestrator"}
        assert all(a["has_override"] is False for a in data)
        assert all(a["enabled"] is True for a in data)

    async def test_get_unknown_key_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents2@example.com")
        resp = await client.get("/backoffice/agents/bogus", headers={"X-User-Id": user_id})
        assert resp.status_code == 404

    async def test_get_slack_default_prompt_mentions_source(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents3@example.com")
        resp = await client.get("/backoffice/agents/slack", headers={"X-User-Id": user_id})
        assert resp.status_code == 200
        assert "slack" in resp.json()["system_prompt"]


class TestUpdateAgent:
    async def test_partial_update_creates_override(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents4@example.com")
        resp = await client.put(
            "/backoffice/agents/slack", json={"model_id": "openai/gpt-4o"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_id"] == "openai/gpt-4o"
        assert data["has_override"] is True
        # Untouched fields stay at their defaults.
        assert data["enabled"] is True

    async def test_unknown_key_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents5@example.com")
        resp = await client.put(
            "/backoffice/agents/bogus", json={"enabled": False}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    async def test_explicit_null_clears_a_previously_set_field(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents6@example.com")
        await client.put(
            "/backoffice/agents/slack", json={"model_id": "openai/gpt-4o"},
            headers={"X-User-Id": user_id},
        )
        resp = await client.put(
            "/backoffice/agents/slack", json={"model_id": None}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["model_id"] is None

    async def test_row_isolation(self, client: AsyncClient) -> None:
        user_a = await _create_user(client, "agents7a@example.com")
        user_b = await _create_user(client, "agents7b@example.com")
        await client.put(
            "/backoffice/agents/slack", json={"model_id": "openai/gpt-4o"},
            headers={"X-User-Id": user_a},
        )
        resp = await client.get("/backoffice/agents/slack", headers={"X-User-Id": user_b})
        assert resp.json()["has_override"] is False


class TestDeleteAgentOverrides:
    async def test_delete_reverts_to_defaults(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents8@example.com")
        await client.put(
            "/backoffice/agents/slack", json={"enabled": False}, headers={"X-User-Id": user_id},
        )
        resp = await client.delete("/backoffice/agents/slack/overrides", headers={"X-User-Id": user_id})
        assert resp.status_code == 204

        after = await client.get("/backoffice/agents/slack", headers={"X-User-Id": user_id})
        assert after.json()["has_override"] is False
        assert after.json()["enabled"] is True

    async def test_delete_with_no_existing_override_is_a_no_op(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "agents9@example.com")
        resp = await client.delete("/backoffice/agents/slack/overrides", headers={"X-User-Id": user_id})
        assert resp.status_code == 204


class TestRunAgentNow:
    async def test_orchestrator_returns_400(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "run1@example.com")
        resp = await client.post("/backoffice/agents/orchestrator/run", headers={"X-User-Id": user_id})
        assert resp.status_code == 400

    async def test_unknown_key_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "run2@example.com")
        resp = await client.post("/backoffice/agents/bogus/run", headers={"X-User-Id": user_id})
        assert resp.status_code == 404

    async def test_disabled_agent_returns_409(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "run3@example.com")
        await client.put(
            "/backoffice/agents/slack", json={"enabled": False}, headers={"X-User-Id": user_id},
        )
        resp = await client.post("/backoffice/agents/slack/run", headers={"X-User-Id": user_id})
        assert resp.status_code == 409

    async def test_disabled_agent_with_prior_run_history_still_returns_409_not_stale_data(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """Regression: a stale AgentRun row from before the agent was
        disabled must never be returned as if it were this call's result."""
        user_id = await _make_persisted_user(db_session, email="run3b@example.com")
        db_session.add(AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.SCHEDULER, status=RunStatus.COMPLETED,
        ))
        await db_session.commit()

        resp = await client.put(
            "/backoffice/agents/slack", json={"enabled": False}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200

        run_resp = await client.post(
            "/backoffice/agents/slack/run", headers={"X-User-Id": str(user_id)},
        )
        assert run_resp.status_code == 409

    async def test_successful_run_returns_the_run_summary(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "run4@example.com")
        fake_agent = MagicMock()
        fake_agent.invoke_async = AsyncMock(return_value="ok")
        fake_agent.messages = []

        with patch(
            "app.services.agent.knowledge.domain_agent.make_domain_agent", return_value=fake_agent,
        ):
            resp = await client.post("/backoffice/agents/slack/run", headers={"X-User-Id": user_id})

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_key"] == "slack"
        assert data["run_type"] == "domain_agent"
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class TestListTools:
    async def test_default_lists_every_agents_tools_deduped(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "tools1@example.com")
        resp = await client.get("/backoffice/tools", headers={"X-User-Id": user_id})
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert "ask_peer_agents" in names
        assert "search_memory" in names

    async def test_scoped_to_slack_excludes_orchestrator_tools(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "tools2@example.com")
        resp = await client.get(
            "/backoffice/tools", params={"agent_key": "slack"}, headers={"X-User-Id": user_id},
        )
        names = {t["name"] for t in resp.json()}
        assert "search_memory" not in names
        assert "get_unprocessed_documents" in names

    async def test_watermark_tools_are_not_configurable(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "tools3@example.com")
        resp = await client.get(
            "/backoffice/tools", params={"agent_key": "slack"}, headers={"X-User-Id": user_id},
        )
        by_name = {t["name"]: t for t in resp.json()}
        assert by_name["get_unprocessed_documents"]["configurable"] is False
        assert by_name["ask_peer_agents"]["configurable"] is True

    async def test_unknown_agent_key_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "tools4@example.com")
        resp = await client.get(
            "/backoffice/tools", params={"agent_key": "bogus"}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

class TestMcpServerUrlValidation:
    """SSRF hardening — a user-supplied MCP server url must not be able to
    target the cloud-metadata endpoint, loopback, or private-network hosts."""

    @pytest.mark.parametrize("bad_url", [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "ftp://mcp.example.com/",
        "not-a-url",
    ])
    async def test_create_rejects_ssrf_targets(self, client: AsyncClient, bad_url: str) -> None:
        user_id = await _create_user(client, f"ssrf{abs(hash(bad_url))}@example.com")
        resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": bad_url},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422

    async def test_create_accepts_a_normal_https_url(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "ssrf_ok@example.com")
        resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://mcp.example.com/api"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201

    async def test_update_also_validates_url(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "ssrf_update@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://mcp.example.com"},
            headers={"X-User-Id": user_id},
        )
        server_id = create_resp.json()["id"]

        resp = await client.put(
            f"/backoffice/mcp-servers/{server_id}",
            json={"url": "http://169.254.169.254/"}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 422


class TestMcpServersCrud:
    async def test_create_never_returns_the_api_key(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp1@example.com")
        resp = await client.post(
            "/backoffice/mcp-servers",
            json={"name": "I+D", "url": "https://mcp.example.com", "api_key": "super-secret"},
            headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["has_api_key"] is True
        assert "api_key" not in data
        assert "api_key_encrypted" not in data

    async def test_list_and_get(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp2@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://s.example.com"},
            headers={"X-User-Id": user_id},
        )
        server_id = create_resp.json()["id"]

        list_resp = await client.get("/backoffice/mcp-servers", headers={"X-User-Id": user_id})
        assert len(list_resp.json()) == 1

        get_resp = await client.get(f"/backoffice/mcp-servers/{server_id}", headers={"X-User-Id": user_id})
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "S"

    async def test_update(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp3@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "Old", "url": "https://s.example.com"},
            headers={"X-User-Id": user_id},
        )
        server_id = create_resp.json()["id"]

        resp = await client.put(
            f"/backoffice/mcp-servers/{server_id}", json={"name": "New"}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    async def test_delete(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp4@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://s.example.com"},
            headers={"X-User-Id": user_id},
        )
        server_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/backoffice/mcp-servers/{server_id}", headers={"X-User-Id": user_id})
        assert del_resp.status_code == 204
        get_resp = await client.get(f"/backoffice/mcp-servers/{server_id}", headers={"X-User-Id": user_id})
        assert get_resp.status_code == 404

    async def test_row_isolation(self, client: AsyncClient) -> None:
        user_a = await _create_user(client, "mcp5a@example.com")
        user_b = await _create_user(client, "mcp5b@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://s.example.com"},
            headers={"X-User-Id": user_a},
        )
        server_id = create_resp.json()["id"]

        resp = await client.get(f"/backoffice/mcp-servers/{server_id}", headers={"X-User-Id": user_b})
        assert resp.status_code == 404

    async def test_get_unknown_id_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp6@example.com")
        resp = await client.get(f"/backoffice/mcp-servers/{uuid.uuid4()}", headers={"X-User-Id": user_id})
        assert resp.status_code == 404

    async def test_test_connection_persists_status_and_tools(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "mcp7@example.com")
        create_resp = await client.post(
            "/backoffice/mcp-servers", json={"name": "S", "url": "https://s.example.com"},
            headers={"X-User-Id": user_id},
        )
        server_id = create_resp.json()["id"]

        mock_client = MagicMock()
        mock_tool = MagicMock()
        mock_tool.tool_name = "list_initiatives"
        mock_tool.tool_spec = {"description": "List initiatives"}
        mock_client.list_tools_sync.return_value = [mock_tool]

        with patch("strands.tools.mcp.MCPClient", return_value=mock_client):
            resp = await client.post(
                f"/backoffice/mcp-servers/{server_id}/test", headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["tools"] == [{"name": "list_initiatives", "description": "List initiatives"}]

        after = await client.get(f"/backoffice/mcp-servers/{server_id}", headers={"X-User-Id": user_id})
        assert after.json()["last_status"] == "ok"
        assert after.json()["discovered_tools"] == [{"name": "list_initiatives", "description": "List initiatives"}]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class TestListAndGetRuns:
    async def test_list_filters_by_agent_key_and_status(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="runs1@example.com")
        db_session.add(AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED,
        ))
        db_session.add(AgentRun(
            user_id=user_id, agent_key="outlook", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.MANUAL, status=RunStatus.FAILED,
        ))
        await db_session.commit()

        resp = await client.get(
            "/backoffice/runs", params={"agent_key": "slack"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_key"] == "slack"

    async def test_stats_round_trips_through_the_list_endpoint(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """AgentRunSummary.stats is free to expose (already loaded on every row,
        no extra query) — this is what lets the Conversations list show a
        negotiation's question/participants without an N+1 fetch per row."""
        user_id = await _make_persisted_user(db_session, email="runs1c@example.com")
        db_session.add(AgentRun(
            user_id=user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED,
            stats={"question": "¿son la misma persona?", "participants": ["slack_negotiator", "outlook_negotiator"]},
        ))
        await db_session.commit()

        resp = await client.get(
            "/backoffice/runs", params={"run_type": "negotiation"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["stats"]["question"] == "¿son la misma persona?"
        assert data[0]["stats"]["participants"] == ["slack_negotiator", "outlook_negotiator"]

    async def test_top_level_excludes_negotiation_sub_runs(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="runs1b@example.com")
        parent = AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED,
        )
        db_session.add(parent)
        await db_session.flush()
        db_session.add(AgentRun(
            user_id=user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED, parent_run_id=parent.id,
        ))
        await db_session.commit()

        resp = await client.get(
            "/backoffice/runs", params={"top_level": "true"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        keys = [r["agent_key"] for r in resp.json()]
        assert keys == ["slack"]

    async def test_get_run_includes_events_and_sub_runs(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="runs2@example.com")
        run = AgentRun(
            user_id=user_id, agent_key="slack", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        await db_session.flush()
        db_session.add(AgentRunEvent(
            run_id=run.id, seq=0, event_type=RunEventType.ASSISTANT_TEXT, payload={"text": "hi"},
        ))
        sub_run = AgentRun(
            user_id=user_id, agent_key="negotiation", run_type=RunType.NEGOTIATION,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED, parent_run_id=run.id,
        )
        db_session.add(sub_run)
        await db_session.commit()

        resp = await client.get(f"/backoffice/runs/{run.id}", headers={"X-User-Id": str(user_id)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["payload"] == {"text": "hi"}
        assert len(data["sub_runs"]) == 1

    async def test_row_isolation(self, client: AsyncClient, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="runs3a@example.com")
        user_b = await _make_persisted_user(db_session, email="runs3b@example.com")
        run = AgentRun(
            user_id=user_a, agent_key="slack", run_type=RunType.DOMAIN_AGENT,
            trigger=RunTrigger.MANUAL, status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        await db_session.commit()

        resp = await client.get(f"/backoffice/runs/{run.id}", headers={"X-User-Id": str(user_b)})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------

class TestGraphEntities:
    async def test_list_search_and_filter(self, client: AsyncClient, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="graph1@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Mariano Ortega")
        await store.create_entity(db_session, user_id, EntityType.PROJECT, "secondBrain")
        await db_session.commit()

        resp = await client.get(
            "/backoffice/graph/entities", params={"search": "mariano"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["canonical_name"] == "Mariano Ortega"

        resp2 = await client.get(
            "/backoffice/graph/entities", params={"entity_type": "project"},
            headers={"X-User-Id": str(user_id)},
        )
        assert len(resp2.json()) == 1
        assert resp2.json()[0]["canonical_name"] == "secondBrain"

    async def test_get_entity_includes_claims_and_links(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="graph2@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await store.add_claim(db_session, entity_a.id, user_id, "slack", "works on X", "slack_domain_agent")
        await store.link_entities(
            db_session, user_id, entity_a.id, entity_b.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.DETERMINISTIC, confidence=1.0,
        )
        await db_session.commit()

        resp = await client.get(
            f"/backoffice/graph/entities/{entity_a.id}", headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["claims"]) == 1
        assert data["claims"][0]["claim_text"] == "works on X"
        assert len(data["links"]) == 1

    async def test_get_unknown_entity_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "graph3@example.com")
        resp = await client.get(
            f"/backoffice/graph/entities/{uuid.uuid4()}", headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    async def test_row_isolation(self, client: AsyncClient, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="graph4a@example.com")
        user_b = await _make_persisted_user(db_session, email="graph4b@example.com")
        entity = await store.create_entity(db_session, user_a, EntityType.PERSON, "A")
        await db_session.commit()

        resp = await client.get(
            f"/backoffice/graph/entities/{entity.id}", headers={"X-User-Id": str(user_b)},
        )
        assert resp.status_code == 404


class TestGraphLinks:
    async def test_list_returns_only_own_links(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_a = await _make_persisted_user(db_session, email="links1a@example.com")
        user_b = await _make_persisted_user(db_session, email="links1b@example.com")
        a1 = await store.create_entity(db_session, user_a, EntityType.PERSON, "A1")
        a2 = await store.create_entity(db_session, user_a, EntityType.PERSON, "A2")
        b1 = await store.create_entity(db_session, user_b, EntityType.PERSON, "B1")
        b2 = await store.create_entity(db_session, user_b, EntityType.PERSON, "B2")
        await store.link_entities(
            db_session, user_a, a1.id, a2.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.DETERMINISTIC, confidence=1.0,
        )
        await store.link_entities(
            db_session, user_b, b1.id, b2.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.DETERMINISTIC, confidence=1.0,
        )
        await db_session.commit()

        resp = await client.get("/backoffice/graph/links", headers={"X-User-Id": str(user_a)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert {data[0]["entity_id_a"], data[0]["entity_id_b"]} == {str(a1.id), str(a2.id)}


class TestGraphQuestions:
    async def test_list_filters_by_status(self, client: AsyncClient, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="q1@example.com")
        await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Quién es X?", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        resp = await client.get(
            "/backoffice/graph/questions", params={"status": "open"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_total_count_header_reflects_full_count_not_just_the_page(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """A limit=1 page must still report the true total via X-Total-Count —
        this is what lets the Preguntas nav badge and pagination show the real
        number instead of silently capping at whatever `limit` the page used."""
        user_id = await _make_persisted_user(db_session, email="q1c@example.com")
        for i in range(3):
            await store.raise_question(
                db_session, user_id, "slack_domain_agent", f"¿Quién es X{i}?", target=QuestionTarget.HUMAN,
            )
        await db_session.commit()

        resp = await client.get(
            "/backoffice/graph/questions",
            params={"status": "open", "limit": 1},
            headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.headers["X-Total-Count"] == "3"

    async def test_resolves_entity_names_from_context(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """A question whose context carries one entity_id resolves entity_name;
        a reconciliation-style question carrying both entity_id and
        candidate_entity_id resolves both — this is what lets the Preguntas
        view show which entity a question is about instead of a raw uuid."""
        user_id = await _make_persisted_user(db_session, email="q1b@example.com")
        juan = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        juan_perez = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan Pérez")
        await db_session.commit()
        await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿trabaja en Atlas?",
            context={"entity_id": str(juan.id)}, target=QuestionTarget.HUMAN,
        )
        await store.raise_question(
            db_session, user_id, "reconciliation_engine", "¿son la misma entidad?",
            context={"entity_id": str(juan.id), "candidate_entity_id": str(juan_perez.id)},
            target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        resp = await client.get(
            "/backoffice/graph/questions", params={"status": "open"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        data = {q["question_text"]: q for q in resp.json()}
        assert data["¿trabaja en Atlas?"]["entity_name"] == "Juan"
        assert data["¿trabaja en Atlas?"]["candidate_entity_name"] is None
        assert data["¿son la misma entidad?"]["entity_name"] == "Juan"
        assert data["¿son la misma entidad?"]["candidate_entity_name"] == "Juan Pérez"

    async def test_answer_closes_the_question(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="q2@example.com")
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Quién es X?", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        resp = await client.post(
            f"/backoffice/graph/questions/{question.id}/answer",
            json={"answer_text": "Es el fundador"}, headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert data["answer_text"] == "Es el fundador"

    async def test_dismiss_closes_without_an_answer(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="q3@example.com")
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Quién es X?", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        resp = await client.post(
            f"/backoffice/graph/questions/{question.id}/dismiss", headers={"X-User-Id": str(user_id)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    async def test_answer_unknown_question_404s(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "q4@example.com")
        resp = await client.post(
            f"/backoffice/graph/questions/{uuid.uuid4()}/answer",
            json={"answer_text": "x"}, headers={"X-User-Id": user_id},
        )
        assert resp.status_code == 404

    async def test_row_isolation(self, client: AsyncClient, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="q5a@example.com")
        user_b = await _make_persisted_user(db_session, email="q5b@example.com")
        question = await store.raise_question(
            db_session, user_a, "slack_domain_agent", "¿Quién es X?", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        resp = await client.post(
            f"/backoffice/graph/questions/{question.id}/dismiss", headers={"X-User-Id": str(user_b)},
        )
        assert resp.status_code == 404
