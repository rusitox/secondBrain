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


def _build_agent(db: AsyncSession, user_id: uuid.UUID, source: str = "slack", embedder: Any = None):
    settings = MagicMock()
    settings.llm_model = "openai/gpt-4o-mini"
    settings.llm_api_key = "sk-test"
    with patch("app.core.config.get_settings", return_value=settings):
        return domain_agent.make_domain_agent(source, db, user_id, embedder=embedder)


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

    async def test_duplicate_mark_does_not_poison_the_session(self, db_session: AsyncSession) -> None:
        """mark_document_processed twice on the same document violates the
        UNIQUE constraint on document_id — that must come back as a tool
        error, not leave the shared AsyncSession unusable for the rest of
        the batch (every tool call in one agent run shares this session)."""
        user_id = await _make_persisted_user(db_session, email="doc4@example.com")
        doc = make_document(user_id=user_id, source="slack")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, user_id)
        first = await _tool(agent, "mark_document_processed")(document_id=str(doc.id))
        assert first == {"marked": True}

        second = await _tool(agent, "mark_document_processed")(document_id=str(doc.id))
        assert "error" in second

        # The session must still be usable for an unrelated subsequent tool call.
        other_doc = make_document(user_id=user_id, source="slack")
        db_session.add(other_doc)
        await db_session.commit()
        results = await _tool(agent, "get_unprocessed_documents")(limit=10)
        assert len(results) == 1
        assert results[0]["document_id"] == str(other_doc.id)

    async def test_mark_document_from_another_user_is_rejected(self, db_session: AsyncSession) -> None:
        owner_id = await _make_persisted_user(db_session, email="doc5owner@example.com")
        other_id = await _make_persisted_user(db_session, email="doc5other@example.com")
        doc = make_document(user_id=owner_id, source="slack")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, other_id)
        result = await _tool(agent, "mark_document_processed")(document_id=str(doc.id))
        assert "error" in result


class TestFindOrCreateEntityTool:
    async def test_embeds_new_entity_when_embedder_given(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ent0@example.com")
        mock_embedder = MagicMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])
        agent = _build_agent(db_session, user_id, embedder=mock_embedder)

        result = await _tool(agent, "find_or_create_entity")(entity_type="person", name="Juan")
        await db_session.commit()

        mock_embedder.embed_single.assert_awaited_once_with("Juan")
        entity = await store.get_entity(db_session, user_id, uuid.UUID(result["entity_id"]))
        assert entity is not None
        assert entity.embedding is not None

    async def test_no_embed_call_when_entity_already_exists(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ent0b@example.com")
        mock_embedder = MagicMock()
        mock_embedder.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])
        agent = _build_agent(db_session, user_id, embedder=mock_embedder)

        await _tool(agent, "find_or_create_entity")(entity_type="person", name="Juan")
        await db_session.commit()
        mock_embedder.embed_single.reset_mock()

        await _tool(agent, "find_or_create_entity")(entity_type="person", name="juan")
        await db_session.commit()

        mock_embedder.embed_single.assert_not_awaited()

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

    async def test_alias_dedup_is_case_insensitive(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ent3@example.com")
        agent = _build_agent(db_session, user_id)

        first = await _tool(agent, "find_or_create_entity")(
            entity_type="person", name="Juan", aliases=["juan"],
        )
        await db_session.commit()

        # A later mention supplies "Juan" as an alias — already present save
        # for case, so it must not be appended as a duplicate.
        await _tool(agent, "find_or_create_entity")(
            entity_type="person", name="juan", aliases=["Juan"],
        )
        await db_session.commit()

        entity = await store.get_entity(db_session, user_id, uuid.UUID(first["entity_id"]))
        assert entity is not None
        assert entity.aliases == ["juan"]


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

    async def test_add_claim_for_nonexistent_entity_errors_without_poisoning_session(
        self, db_session: AsyncSession
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="claim3@example.com")
        agent = _build_agent(db_session, user_id)

        result = await _tool(agent, "add_claim")(
            entity_id=str(uuid.uuid4()), claim_text="huérfano",
        )
        assert "error" in result

        # Session must still work for a subsequent, unrelated call.
        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="X")
        assert entity["created"] is True

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
    async def test_no_relevant_peer_claims_returns_unresolved(self, db_session: AsyncSession) -> None:
        """Peers ARE registered (Phase 2+), but none holds a claim about this
        brand-new entity — still nothing to negotiate."""
        user_id = await _make_persisted_user(db_session, email="peer1@example.com")
        agent = _build_agent(db_session, user_id)

        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="X")
        await db_session.commit()

        result = await _tool(agent, "ask_peer_agents")(entity_id=entity["entity_id"], question="¿duda?")
        assert result == {
            "resolved": False, "answer": None, "confidence": None,
            "peers_consulted": [], "question_id": None,
        }


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

    async def test_disputed_peer_claim_does_not_count_as_relevant(
        self, db_session: AsyncSession
    ) -> None:
        """A DISPUTED (already-contradicted) claim must not be treated as
        settled fact — the same rung-1 filter consult_knowledge_base applies."""
        from app.models.entity_claim import ClaimStatus

        user_id = await _make_persisted_user(db_session, email="neg5@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "claim", "slack_domain_agent")
        await store.add_claim(
            db_session, entity.id, user_id, "outlook", "claim disputado", "outlook_domain_agent",
            status=ClaimStatus.DISPUTED,
        )
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

        assert result["resolved"] is True
        assert result["answer"] == "Sí, es la misma persona"
        assert result["confidence"] == 0.9
        assert result["peers_consulted"] == ["outlook"]
        assert result["question_id"] is not None
        # One negotiator per side: the asking source + the relevant peer.
        assert mock_agent_cls.call_count == 2
        mock_swarm_cls.assert_called_once()
        mock_swarm_instance.invoke_async.assert_awaited_once()

        # The negotiation's outcome was persisted, not left for the caller's
        # next turn to remember to record — it's already answered, not open.
        open_questions = await store.list_open_questions(db_session, user_id)
        assert result["question_id"] not in {str(q.id) for q in open_questions}

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

        # A crashed negotiation still escalates to the human rather than
        # vanishing silently — the plan's "nunca en silencio" invariant.
        human_questions = await store.list_open_questions(db_session, user_id, target=QuestionTarget.HUMAN)
        assert len(human_questions) == 1

    async def test_second_call_for_same_entity_reuses_pending_question(
        self, db_session: AsyncSession
    ) -> None:
        """Rate-limit guard: a batch that hits the same ambiguous entity twice
        must not spin up a second Swarm while the first is still unresolved."""
        user_id = await _make_persisted_user(db_session, email="neg4@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "W")
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
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance) as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            first = await domain_agent._ask_peer_agents(db_session, user_id, "slack", entity.id, "¿duda?")
            second = await domain_agent._ask_peer_agents(db_session, user_id, "slack", entity.id, "¿duda de nuevo?")

        assert mock_swarm_cls.call_count == 1  # only the first call negotiated
        assert second["question_id"] == first["question_id"]
        assert second["peers_consulted"] == []


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

        mock_make.assert_called_once_with("slack", db_session, user_id, embedder=None)
        task_arg = fake_agent.invoke_async.call_args.args[0]
        assert "5" in task_arg
        assert "slack" in task_arg
        assert result == {"source": "slack", "summary": "ok"}


# ---------------------------------------------------------------------------
# Phase 2 — replicating the pattern to Outlook, Teams, Fathom.
#
# make_domain_agent has no source-specific branching, so these don't re-test
# the tool logic itself (already covered above) — just that each source is
# correctly wired: right guidance in the prompt, right document scoping, and
# that ask_peer_agents now has *real* cross-source peers to negotiate with.
# ---------------------------------------------------------------------------

class TestPhase2SourceRegistration:
    def test_all_four_sources_registered(self) -> None:
        assert {"slack", "outlook", "teams", "fathom"}.issubset(domain_agent.REGISTERED_SOURCES)

    @pytest.mark.parametrize("source", ["outlook", "teams", "fathom"])
    async def test_system_prompt_contains_source_guidance(
        self, db_session: AsyncSession, source: str
    ) -> None:
        user_id = await _make_persisted_user(db_session, email=f"{source}reg@example.com")
        agent = _build_agent(db_session, user_id, source=source)
        assert source in agent.system_prompt
        assert domain_agent._SOURCE_GUIDANCE[source] in agent.system_prompt


class TestPhase2DocumentScoping:
    @pytest.mark.parametrize("source", ["outlook", "teams", "fathom"])
    async def test_only_sees_documents_from_its_own_source(
        self, db_session: AsyncSession, source: str
    ) -> None:
        user_id = await _make_persisted_user(db_session, email=f"{source}scope@example.com")
        db_session.add(make_document(user_id=user_id, source=source, content="mine"))
        db_session.add(make_document(user_id=user_id, source="slack", content="not mine"))
        await db_session.commit()

        agent = _build_agent(db_session, user_id, source=source)
        results = await _tool(agent, "get_unprocessed_documents")(limit=10)

        assert len(results) == 1
        assert results[0]["content"] == "mine"


class TestPhase2FullExtractionFlow:
    @pytest.mark.parametrize("source", ["outlook", "teams", "fathom"])
    async def test_extract_entity_and_claim_then_mark_processed(
        self, db_session: AsyncSession, source: str
    ) -> None:
        """Proves the whole tool chain — not just Slack's — end to end."""
        user_id = await _make_persisted_user(db_session, email=f"{source}flow@example.com")
        doc = make_document(user_id=user_id, source=source, content="Juan lidera el proyecto Atlas")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, user_id, source=source)
        docs = await _tool(agent, "get_unprocessed_documents")(limit=10)
        assert len(docs) == 1

        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="Juan")
        await db_session.commit()
        claim = await _tool(agent, "add_claim")(
            entity_id=entity["entity_id"], claim_text="Lidera el proyecto Atlas", confidence=0.7,
        )
        await db_session.commit()
        assert "claim_id" in claim

        await _tool(agent, "mark_document_processed")(document_id=doc.id.__str__())
        await db_session.commit()
        assert await _tool(agent, "get_unprocessed_documents")(limit=10) == []


class TestPhase2CrossSourceNegotiation:
    async def test_slack_agent_finds_real_outlook_peer_without_patching_registry(
        self, db_session: AsyncSession
    ) -> None:
        """The point of Phase 2: ask_peer_agents now has a genuine peer to
        negotiate with, with REGISTERED_SOURCES exactly as shipped — no
        patch.object needed, unlike every Phase 1 negotiation test."""
        user_id = await _make_persisted_user(db_session, email="cross1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "trabaja en Atlas", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "outlook", "email juan@x.com", "outlook_domain_agent")
        await db_session.commit()

        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"
        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(return_value=MagicMock())

        with patch("strands.Agent", return_value=MagicMock()) as mock_agent_cls, \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance) as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            result = await domain_agent._ask_peer_agents(
                db_session, user_id, "slack", entity.id, "¿Es la misma persona que en Outlook?",
            )

        assert result["peers_consulted"] == ["outlook"]
        mock_swarm_cls.assert_called_once()
        assert mock_agent_cls.call_count == 2


# ---------------------------------------------------------------------------
# Phase 3 — Notion. Separate phase because app/services/notion/ already has
# its own bidirectional sync (NotionSync) and publisher — this domain agent
# must be read-only towards the shared knowledge layer and must never import
# or call anything that writes back to Notion.
# ---------------------------------------------------------------------------

class TestPhase3NotionRegistration:
    def test_notion_registered(self) -> None:
        assert "notion" in domain_agent.REGISTERED_SOURCES

    async def test_system_prompt_contains_notion_guidance(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="notionreg@example.com")
        agent = _build_agent(db_session, user_id, source="notion")
        assert domain_agent._SOURCE_GUIDANCE["notion"] in agent.system_prompt

    def test_domain_agent_module_never_imports_notion_write_path(self) -> None:
        """Architectural guard for the plan's own constraint: this agent reads
        Documents already ingested by the existing pipeline — it must never
        touch app.services.notion (NotionSync/NotionPublisher), which is the
        only thing allowed to write back to Notion."""
        import inspect

        source_code = inspect.getsource(domain_agent)
        assert "app.services.notion" not in source_code


class TestPhase3DocumentScoping:
    async def test_only_sees_notion_documents(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="notionscope@example.com")
        db_session.add(make_document(user_id=user_id, source="notion", content="mine"))
        db_session.add(make_document(user_id=user_id, source="slack", content="not mine"))
        await db_session.commit()

        agent = _build_agent(db_session, user_id, source="notion")
        results = await _tool(agent, "get_unprocessed_documents")(limit=10)

        assert len(results) == 1
        assert results[0]["content"] == "mine"


class TestPhase3FullExtractionFlow:
    async def test_extract_entity_and_claim_then_mark_processed(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="notionflow@example.com")
        doc = make_document(user_id=user_id, source="notion", content="Juan lidera el proyecto Atlas")
        db_session.add(doc)
        await db_session.commit()

        agent = _build_agent(db_session, user_id, source="notion")
        docs = await _tool(agent, "get_unprocessed_documents")(limit=10)
        assert len(docs) == 1

        entity = await _tool(agent, "find_or_create_entity")(entity_type="person", name="Juan")
        await db_session.commit()
        claim = await _tool(agent, "add_claim")(
            entity_id=entity["entity_id"], claim_text="Lidera el proyecto Atlas", confidence=0.7,
        )
        await db_session.commit()
        assert "claim_id" in claim

        await _tool(agent, "mark_document_processed")(document_id=doc.id.__str__())
        await db_session.commit()
        assert await _tool(agent, "get_unprocessed_documents")(limit=10) == []
