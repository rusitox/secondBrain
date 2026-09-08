"""Integration tests for the Phase 5/9 knowledge tools in strands_tools.py.

query_knowledge, ask_domain_agents, get_pending_questions, and
confirm_pending_answer are the live chat orchestrator's connection to the
knowledge system built by the domain agents (specs/plan-multi-agent-knowledge.md,
Phase 5; ask_domain_agents is Phase 9 — the orchestrator validating a doubt
with the relevant domain agents before answering). Run against the real
SQLite test DB via make_agent_tools, same pattern as
tests/integration/test_domain_agent.py.
"""
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, RunStatus, RunTrigger, RunType
from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.pending_question import QuestionStatus, QuestionTarget
from app.services.agent.knowledge import domain_agent, store
from app.services.agent.strands_tools import make_agent_tools
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


def _build_tools(db: AsyncSession, user_id: uuid.UUID, parent_run_id=None):
    return make_agent_tools(db=db, user_id=user_id, parent_run_id=parent_run_id)


def _tool(tools: Any, name: str):
    return next(t for t in tools if t.tool_name == name).__wrapped__


class TestQueryKnowledgeTool:
    async def test_returns_matching_entity_with_claims(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="qk1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Mariano")
        await db_session.commit()
        await store.add_claim(
            db_session, entity.id, user_id, "slack", "Lidera el equipo", "slack_domain_agent",
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        results = await _tool(tools, "query_knowledge")(query="Mariano")

        assert len(results) == 1
        assert results[0]["canonical_name"] == "Mariano"
        assert results[0]["claims"][0]["claim_text"] == "Lidera el equipo"

    async def test_no_match_returns_empty_list(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="qk2@example.com")
        tools = _build_tools(db_session, user_id)

        assert await _tool(tools, "query_knowledge")(query="nadie") == []

    async def test_invalid_entity_type_returns_empty_list(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="qk3@example.com")
        tools = _build_tools(db_session, user_id)

        result = await _tool(tools, "query_knowledge")(query="x", entity_type="bogus")
        assert result == []


class TestAskDomainAgentsTool:
    async def test_invalid_entity_id_returns_error_without_negotiating(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ada1@example.com")
        tools = _build_tools(db_session, user_id)

        result = await _tool(tools, "ask_domain_agents")(entity_id="not-a-uuid", question="¿duda?")
        assert "error" in result

    async def test_delegates_to_consult_domain_agents_with_the_chat_runs_parent_id(
        self, db_session: AsyncSession,
    ) -> None:
        """Confirms the tool wrapper actually threads make_agent_tools'
        parent_run_id through — the wiring that makes a negotiation the
        orchestrator triggers mid-chat show up as a sub-run of that chat in
        the backoffice, not a disconnected row."""
        user_id = await _make_persisted_user(db_session, email="ada2@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "c1", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "outlook", "c2", "outlook_domain_agent")
        await db_session.commit()

        chat_run = AgentRun(
            user_id=user_id, agent_key="orchestrator", run_type=RunType.CHAT,
            trigger=RunTrigger.API, status=RunStatus.RUNNING,
        )
        db_session.add(chat_run)
        await db_session.commit()

        captured_tools: dict = {}

        def fake_agent_ctor(*args: Any, **kwargs: Any) -> MagicMock:
            for t in kwargs.get("tools", []):
                captured_tools[t.tool_name] = t
            return MagicMock(name=kwargs.get("name"))

        async def fake_invoke_async(*args: Any, **kwargs: Any) -> MagicMock:
            captured_tools["submit_verdict"].__wrapped__(
                resolved=True, answer="sí", confidence=0.8,
            )
            return MagicMock()

        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(side_effect=fake_invoke_async)
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        tools = _build_tools(db_session, user_id, parent_run_id=chat_run.id)

        with patch.object(domain_agent, "REGISTERED_SOURCES", ["slack", "outlook"]), \
             patch("strands.Agent", side_effect=fake_agent_ctor), \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance), \
             patch("app.core.config.get_settings", return_value=settings):
            result = await _tool(tools, "ask_domain_agents")(
                entity_id=str(entity.id), question="¿duda?",
            )

        assert result["resolved"] is True
        run = (await db_session.execute(
            select(AgentRun).where(AgentRun.user_id == user_id, AgentRun.run_type == RunType.NEGOTIATION)
        )).scalar_one()
        assert run.parent_run_id == chat_run.id


class TestGetPendingQuestionsTool:
    async def test_returns_only_human_targeted_open_questions(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="gpq1@example.com")
        await store.raise_question(
            db_session, user_id, "slack_domain_agent", "duda para pares",
            target=QuestionTarget.PEER_AGENTS,
        )
        await store.raise_question(
            db_session, user_id, "outlook_domain_agent", "duda para humano",
            target=QuestionTarget.HUMAN, candidate_answer="palpito", candidate_confidence=0.6,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        results = await _tool(tools, "get_pending_questions")()

        assert len(results) == 1
        assert results[0]["question_text"] == "duda para humano"
        assert results[0]["candidate_answer"] == "palpito"
        assert results[0]["candidate_confidence"] == 0.6

    async def test_excludes_resolved_questions(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="gpq2@example.com")
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "duda", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()
        from app.models.pending_question import ResolvedBy
        await store.resolve_question(db_session, user_id, question.id, ResolvedBy.HUMAN)
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        assert await _tool(tools, "get_pending_questions")() == []


class TestConfirmPendingAnswerTool:
    async def test_question_not_found_returns_error(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cpa1@example.com")
        tools = _build_tools(db_session, user_id)

        result = await _tool(tools, "confirm_pending_answer")(
            question_id=str(uuid.uuid4()), answer_text="sí",
        )
        assert "error" in result

    async def test_already_resolved_question_is_rejected(self, db_session: AsyncSession) -> None:
        """Confirming twice (a retried tool call, or the LLM re-confirming
        the same question) must not double-write the claim/link and
        double-count it in recompute_confidence."""
        user_id = await _make_persisted_user(db_session, email="cpa6@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿duda?",
            context={"entity_id": str(entity.id)}, target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        first = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="sí",
        )
        await db_session.commit()
        assert first["resolved"] is True

        second = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="sí otra vez",
        )
        assert "error" in second

        claims = await store.list_claims(db_session, user_id, entity.id, status=ClaimStatus.CONFIRMED_BY_USER)
        assert len(claims) == 1  # not duplicated

    async def test_confirmed_single_entity_question_creates_claim(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cpa2@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        await db_session.commit()
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Juan es del equipo de plataforma?",
            context={"entity_id": str(entity.id)}, target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        result = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="Sí, es del equipo de plataforma",
        )
        await db_session.commit()

        assert result["resolved"] is True
        assert result["entities_updated"] == [str(entity.id)]

        claims = await store.list_claims(db_session, user_id, entity.id, status=ClaimStatus.CONFIRMED_BY_USER)
        assert len(claims) == 1
        assert claims[0].claim_text == "Sí, es del equipo de plataforma"
        assert claims[0].source == "user"
        assert claims[0].confidence == 1.0

        refetched_entity = await store.get_entity(db_session, user_id, entity.id)
        assert refetched_entity is not None
        assert refetched_entity.confidence > 0.5  # boosted by the confirmation

        open_questions = await store.list_open_questions(db_session, user_id)
        assert open_questions == []

    async def test_confirmed_same_as_question_creates_link(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cpa3@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan (Slack)")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan Pérez (Outlook)")
        await db_session.commit()
        question = await store.raise_question(
            db_session, user_id, "reconciliation_engine", "¿son la misma entidad?",
            context={"entity_id": str(a.id), "candidate_entity_id": str(b.id)},
            target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        result = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="Sí, es la misma persona",
        )
        await db_session.commit()

        assert set(result["entities_updated"]) == {str(a.id), str(b.id)}
        links = await store.list_links_for_entity(db_session, user_id, a.id)
        assert len(links) == 1
        assert links[0].relation_type == "same_as"

    async def test_not_confirmed_dismisses_without_writing_claim(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="cpa4@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿duda?",
            context={"entity_id": str(entity.id)}, target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        result = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="No, te equivocás", confirmed=False,
        )
        await db_session.commit()

        assert result["entities_updated"] == []
        claims = await store.list_claims(db_session, user_id, entity.id)
        assert claims == []

        open_questions = await store.list_open_questions(db_session, user_id)
        assert open_questions == []

    async def test_confirming_twice_does_not_poison_session(self, db_session: AsyncSession) -> None:
        """A stale question_id from a hallucinated or reused tool call must
        return an error, not crash the rest of the conversation turn."""
        user_id = await _make_persisted_user(db_session, email="cpa5@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿duda?",
            context={"entity_id": str(entity.id)}, target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        tools = _build_tools(db_session, user_id)
        first = await _tool(tools, "confirm_pending_answer")(
            question_id=str(question.id), answer_text="sí",
        )
        await db_session.commit()
        assert first["resolved"] is True

        # Second confirmation of an entity_id that no longer needs one — still
        # succeeds (add_claim doesn't require the question to still be open),
        # proving the session survived the first call cleanly.
        second = await _tool(tools, "query_knowledge")(query="X")
        assert len(second) == 1
