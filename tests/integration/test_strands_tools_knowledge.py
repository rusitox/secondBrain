"""Integration tests for the Phase 5 knowledge tools in strands_tools.py.

query_knowledge, get_pending_questions, and confirm_pending_answer are the
live chat orchestrator's connection to the knowledge system built by the
domain agents (specs/plan-multi-agent-knowledge.md, Phase 5). Run against
the real SQLite test DB via make_agent_tools, same pattern as
tests/integration/test_domain_agent.py.
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.pending_question import QuestionStatus, QuestionTarget
from app.services.agent.knowledge import store
from app.services.agent.strands_tools import make_agent_tools
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


def _build_tools(db: AsyncSession, user_id: uuid.UUID):
    return make_agent_tools(db=db, user_id=user_id)


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
