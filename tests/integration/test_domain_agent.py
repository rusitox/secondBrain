"""Integration tests for the Phase 1 reference domain agent (Slack).

Tool closures run against the real SQLite test DB (db_session) — only the
Strands Agent/Swarm layer is mocked, since that's what would otherwise hit
a real LLM. See specs/plan-multi-agent-knowledge.md.
"""
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.pending_question import QuestionTarget
from app.services.agent.knowledge import domain_agent, store
from tests.factories import make_document, make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


def _build_agent(db: AsyncSession, user_id: uuid.UUID, source: str = "slack"):
    settings = MagicMock()
    settings.llm_model = "openai/gpt-4o-mini"
    settings.llm_api_key = "sk-test"
    with patch("app.core.config.get_settings", return_value=settings):
        return domain_agent.make_domain_agent(source, db, user_id)


def _tool(agent: Any, name: str):
    return agent.tool_registry.registry[name].__wrapped__


class TestMakeDomainAgent:
    async def test_registers_all_ladder_tools(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="agent1@example.com")
        agent = _build_agent(db_session, user_id)

        tool_names = set(agent.tool_registry.registry.keys())
        assert tool_names == {
            "get_unprocessed_documents",
            "mark_document_processed",
            "find_or_create_entity",
            "add_claim",
            "consult_knowledge_base",
            "ask_peer_agents",
            "escalate_or_validate",
        }

    async def test_system_prompt_mentions_source(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="agent2@example.com")
        agent = _build_agent(db_session, user_id)
        assert "slack" in agent.system_prompt


class TestGetAndMarkUnprocessedDocuments:
    async def test_returns_new_documents(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="doc1@example.com")
        doc = make_document(user_id=user_id, source="slack", content="hola equipo")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, user_id)
        results = await _tool(agent, "get_unprocessed_documents")(limit=10)

        assert len(results) == 1
        assert results[0]["content"] == "hola equipo"
        assert results[0]["document_id"] == str(doc.id)

    async def test_ignores_documents_from_other_sources(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="doc2@example.com")
        db_session.add(make_document(user_id=user_id, source="outlook", content="email"))
        await db_session.commit()

        agent = _build_agent(db_session, user_id)
        results = await _tool(agent, "get_unprocessed_documents")(limit=10)
        assert results == []

    async def test_mark_processed_excludes_from_next_fetch(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="doc3@example.com")
        doc = make_document(user_id=user_id, source="slack")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, user_id)
        await _tool(agent, "mark_document_processed")(document_id=str(doc.id))
        await db_session.commit()

        results = await _tool(agent, "get_unprocessed_documents")(limit=10)
        assert results == []


class TestFindOrCreateEntityTool:
    async def test_creates_then_finds_case_insensitively(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ent1@example.com")
        agent = _build_agent(db_session, user_id)

        first = await _tool(agent, "find_or_create_entity")(entity_type="person", name="Juan")
        await db_session.commit()
        assert first["created"] is True

        second = await _tool(agent, "find_or_create_entity")(entity_type="person", name="juan")
        await db_session.commit()
        assert second["created"] is False
        assert second["entity_id"] == first["entity_id"]

    async def test_invalid_entity_type_returns_error_dict(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ent2@example.com")
        agent = _build_agent(db_session, user_id)

        result = await _tool(agent, "find_or_create_entity")(entity_type="bogus", name="X")
        assert "error" in result


class TestAddClaimAndConsultKnowledgeBase:
    async def test_claim_is_visible_via_consult_knowledge_base(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="claim1@example.com")
        agent = _build_agent(db_session, user_id)

        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="Mariano")
        await db_session.commit()
        claim = await _tool(agent, "add_claim")(
            entity_id=entity["entity_id"],
            claim_text="Lidera el equipo de plataforma",
            confidence=0.8,
        )
        await db_session.commit()
        assert "claim_id" in claim

        kb_results = await _tool(agent, "consult_knowledge_base")(query="Mariano")
        assert len(kb_results) == 1
        assert kb_results[0]["claims"][0]["claim_text"] == "Lidera el equipo de plataforma"

    async def test_invalid_entity_type_returns_empty_list(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="claim2@example.com")
        agent = _build_agent(db_session, user_id)

        result = await _tool(agent, "consult_knowledge_base")(query="x", entity_type="bogus")
        assert result == []


class TestEscalateOrValidateTool:
    async def test_creates_pending_question_targeting_human(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="esc1@example.com")
        agent = _build_agent(db_session, user_id)

        result = await _tool(agent, "escalate_or_validate")(
            question_text="¿Es la misma persona que en Outlook?",
            candidate_answer="Creemos que sí",
            candidate_confidence=0.6,
        )
        await db_session.commit()
        assert "question_id" in result

        open_questions = await store.list_open_questions(db_session, user_id, target=QuestionTarget.HUMAN)
        assert len(open_questions) == 1
        assert open_questions[0].candidate_answer == "Creemos que sí"
        assert open_questions[0].raised_by_agent == "slack_domain_agent"


class TestAskPeerAgentsTool:
    async def test_no_peers_registered_returns_unresolved(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="peer1@example.com")
        agent = _build_agent(db_session, user_id)

        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="X")
        await db_session.commit()

        result = await _tool(agent, "ask_peer_agents")(entity_id=entity["entity_id"], question="¿duda?")
        assert result == {"resolved": False, "answer": None, "confidence": None, "peers_consulted": []}


class TestAskPeerAgentsNegotiation:
    """Exercises _ask_peer_agents directly with fake registered peers — the
    only way to test the Swarm negotiation path without >1 real domain agent."""

    async def test_no_relevant_peer_claims_short_circuits_without_swarm(
        self, db_session: AsyncSession
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="neg1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()
        # Only slack has a claim — "outlook" is a registered peer but has nothing to add.
        await store.add_claim(db_session, entity.id, user_id, "slack", "claim", "slack_domain_agent")
        await db_session.commit()

        with patch.object(domain_agent, "REGISTERED_SOURCES", ["slack", "outlook"]), \
             patch("strands.multiagent.Swarm") as mock_swarm_cls:
            result = await domain_agent._ask_peer_agents(
                db_session, user_id, "slack", entity.id, "¿duda?"
            )

        assert result["peers_consulted"] == []
        mock_swarm_cls.assert_not_called()

    async def test_relevant_peer_negotiates_via_swarm(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="neg2@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "trabaja en Atlas", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "outlook", "email juan@x.com", "outlook_domain_agent")
        await db_session.commit()

        captured_tools: Dict[str, Any] = {}

        def fake_agent_ctor(*args: Any, **kwargs: Any) -> MagicMock:
            for t in kwargs.get("tools", []):
                captured_tools[t.tool_name] = t
            return MagicMock(name=kwargs.get("name"))

        async def fake_invoke_async(*args: Any, **kwargs: Any) -> MagicMock:
            # Simulate the negotiation concluding: some agent called submit_verdict.
            captured_tools["submit_verdict"].__wrapped__(
                resolved=True, answer="Sí, es la misma persona", confidence=0.9,
            )
            return MagicMock()

        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(side_effect=fake_invoke_async)

        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        with patch.object(domain_agent, "REGISTERED_SOURCES", ["slack", "outlook"]), \
             patch("strands.Agent", side_effect=fake_agent_ctor) as mock_agent_cls, \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance) as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            result = await domain_agent._ask_peer_agents(
                db_session, user_id, "slack", entity.id, "¿Es la misma persona que en Outlook?",
            )

        assert result == {
            "resolved": True,
            "answer": "Sí, es la misma persona",
            "confidence": 0.9,
            "peers_consulted": ["outlook"],
        }
        # One negotiator per side: the asking source + the relevant peer.
        assert mock_agent_cls.call_count == 2
        mock_swarm_cls.assert_called_once()
        mock_swarm_instance.invoke_async.assert_awaited_once()

    async def test_swarm_exception_falls_back_to_unresolved(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="neg3@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Z")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "c1", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "outlook", "c2", "outlook_domain_agent")
        await db_session.commit()

        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(side_effect=RuntimeError("boom"))

        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        with patch.object(domain_agent, "REGISTERED_SOURCES", ["slack", "outlook"]), \
             patch("strands.Agent", return_value=MagicMock()), \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance), \
             patch("app.core.config.get_settings", return_value=settings):
            result = await domain_agent._ask_peer_agents(
                db_session, user_id, "slack", entity.id, "¿duda?"
            )

        assert result["resolved"] is False
        assert result["peers_consulted"] == ["outlook"]


class TestSubmitVerdictTool:
    async def test_mutates_verdict_dict(self) -> None:
        verdict: Dict[str, Any] = {"resolved": False, "answer": None, "confidence": None}
        tool = domain_agent._make_submit_verdict_tool(verdict)

        result = tool.__wrapped__(resolved=True, answer="listo", confidence=0.7)

        assert result == {"recorded": True}
        assert verdict == {"resolved": True, "answer": "listo", "confidence": 0.7}


class TestRunDomainAgent:
    async def test_invokes_agent_with_batch_size_in_task(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="run1@example.com")
        fake_agent = MagicMock()
        fake_agent.invoke_async = AsyncMock(return_value="ok")

        with patch.object(domain_agent, "make_domain_agent", return_value=fake_agent) as mock_make:
            result = await domain_agent.run_domain_agent(
                "slack", db_session, user_id, batch_size=5
            )

        mock_make.assert_called_once_with("slack", db_session, user_id)
        task_arg = fake_agent.invoke_async.call_args.args[0]
        assert "5" in task_arg
        assert "slack" in task_arg
        assert result == {"source": "slack", "summary": "ok"}
