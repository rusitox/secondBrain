"""Integration tests for the Phase 4 reconciliation engine.

Embedding-similarity search (store.find_similar_entities) needs pgvector and
isn't exercised here — see tests/unit/test_reconciliation.py for the
pairing/dedup logic tested against a mocked store. Everything else (email
matching, confidence, the Swarm negotiation with Strands mocked, and the
orchestration in run_reconciliation) runs against the real SQLite test DB.
"""
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionTarget
from app.services.agent.knowledge import reconciliation, store
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


class TestAutoLinkByEmail:
    async def test_links_people_sharing_an_email(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="a1@example.com")
        a = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "Juan (Slack)",
            attributes={"email": "Juan.Perez@empresa.com"},
        )
        b = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "Juan Pérez (Outlook)",
            attributes={"email": "juan.perez@empresa.com"},
        )
        await db_session.commit()

        created = await reconciliation.auto_link_by_email(db_session, user_id)
        await db_session.commit()

        assert len(created) == 1
        links = await store.list_links_for_entity(db_session, user_id, a.id)
        assert len(links) == 1
        assert links[0].relation_type == "same_as"
        assert links[0].resolved_by == LinkResolvedBy.DETERMINISTIC
        assert links[0].confidence == 1.0
        assert {links[0].entity_id_a, links[0].entity_id_b} == {a.id, b.id}

    async def test_skips_people_without_email(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="a2@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()

        created = await reconciliation.auto_link_by_email(db_session, user_id)
        assert created == []

    async def test_does_not_duplicate_an_existing_link(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="a3@example.com")
        a = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "A", attributes={"email": "x@y.com"},
        )
        b = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "B", attributes={"email": "x@y.com"},
        )
        await db_session.commit()

        first = await reconciliation.auto_link_by_email(db_session, user_id)
        await db_session.commit()
        assert len(first) == 1

        second = await reconciliation.auto_link_by_email(db_session, user_id)
        assert second == []

        links = await store.list_links_for_entity(db_session, user_id, a.id)
        assert len(links) == 1


class TestRecomputeConfidence:
    async def test_single_source_stays_near_base(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "c", "slack_domain_agent")
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, entity.id)
        assert confidence == 0.5

    async def test_rises_with_corroborating_sources(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c2@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "c1", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "outlook", "c2", "outlook_domain_agent")
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, entity.id)
        assert confidence == 0.65  # 0.5 + 0.15 * (2 sources - 1)

    async def test_drops_with_unresolved_dispute(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c3@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "c1", "slack_domain_agent")
        await store.add_claim(
            db_session, entity.id, user_id, "outlook", "c2", "outlook_domain_agent",
            status=ClaimStatus.DISPUTED,
        )
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, entity.id)
        assert confidence == 0.3  # 0.5 - 0.2, DISPUTED doesn't count as an active source

    async def test_rises_with_user_confirmation(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c4@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        await store.add_claim(
            db_session, entity.id, user_id, "user", "confirmado", "orchestrator",
            status=ClaimStatus.CONFIRMED_BY_USER,
        )
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, entity.id)
        assert confidence == 0.7  # 0.5 + 0.2

    async def test_rises_with_same_as_link(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c5@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await db_session.commit()
        await store.link_entities(
            db_session, user_id, a.id, b.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.SWARM, confidence=0.9,
        )
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, a.id)
        assert confidence == 0.6  # 0.5 + 0.1

    async def test_clamped_to_one(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c6@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        for src in ["slack", "outlook", "teams", "fathom", "notion"]:
            await store.add_claim(db_session, entity.id, user_id, src, "c", f"{src}_domain_agent")
        await store.add_claim(
            db_session, entity.id, user_id, "user", "confirmado", "orchestrator",
            status=ClaimStatus.CONFIRMED_BY_USER,
        )
        await db_session.commit()

        confidence = await reconciliation.recompute_confidence(db_session, user_id, entity.id)
        assert confidence == 1.0


class TestNegotiateSameAs:
    async def test_resolves_via_swarm(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="n1@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan Pérez")
        await db_session.commit()
        await store.add_claim(db_session, a.id, user_id, "slack", "trabaja en Atlas", "slack_domain_agent")
        await store.add_claim(db_session, b.id, user_id, "outlook", "email juan@x.com", "outlook_domain_agent")
        await db_session.commit()

        captured_tools: Dict[str, Any] = {}

        def fake_agent_ctor(*args: Any, **kwargs: Any) -> MagicMock:
            for t in kwargs.get("tools", []):
                captured_tools[t.tool_name] = t
            return MagicMock(name=kwargs.get("name"))

        async def fake_invoke_async(*args: Any, **kwargs: Any) -> MagicMock:
            captured_tools["submit_same_as_verdict"].__wrapped__(
                same_entity=True, confidence=0.9, reasoning="mismo email",
            )
            return MagicMock()

        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(side_effect=fake_invoke_async)
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        with patch("strands.Agent", side_effect=fake_agent_ctor) as mock_agent_cls, \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance) as mock_swarm_cls, \
             patch("app.core.config.get_settings", return_value=settings):
            verdict = await reconciliation.negotiate_same_as(db_session, user_id, a, b)

        assert verdict == {"same_entity": True, "confidence": 0.9, "reasoning": "mismo email"}
        assert mock_agent_cls.call_count == 2
        mock_swarm_cls.assert_called_once()

    async def test_swarm_exception_returns_unresolved_default(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="n2@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()

        mock_swarm_instance = MagicMock()
        mock_swarm_instance.invoke_async = AsyncMock(side_effect=RuntimeError("boom"))
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        with patch("strands.Agent", return_value=MagicMock()), \
             patch("strands.multiagent.Swarm", return_value=mock_swarm_instance), \
             patch("app.core.config.get_settings", return_value=settings):
            verdict = await reconciliation.negotiate_same_as(db_session, user_id, a, b)

        assert verdict == {"same_entity": False, "confidence": None, "reasoning": None}


class TestRunReconciliation:
    async def test_creates_link_when_negotiation_is_confident(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="r1@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan Pérez")
        await db_session.commit()

        with patch.object(
            reconciliation, "find_candidate_duplicates", AsyncMock(return_value=[(a, b)]),
        ), patch.object(
            reconciliation, "negotiate_same_as",
            AsyncMock(return_value={"same_entity": True, "confidence": 0.9, "reasoning": "ok"}),
        ):
            result = await reconciliation.run_reconciliation(db_session, user_id)
        await db_session.commit()

        assert result["negotiated"] == 1
        assert result["escalated"] == 0
        links = await store.list_links_for_entity(db_session, user_id, a.id)
        assert len(links) == 1
        assert links[0].resolved_by == LinkResolvedBy.SWARM

    async def test_escalates_when_negotiation_is_not_confident(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="r2@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()

        with patch.object(
            reconciliation, "find_candidate_duplicates", AsyncMock(return_value=[(a, b)]),
        ), patch.object(
            reconciliation, "negotiate_same_as",
            AsyncMock(return_value={"same_entity": False, "confidence": None, "reasoning": None}),
        ):
            result = await reconciliation.run_reconciliation(db_session, user_id)
        await db_session.commit()

        assert result["negotiated"] == 0
        assert result["escalated"] == 1
        open_questions = await store.list_open_questions(db_session, user_id, target=QuestionTarget.HUMAN)
        assert len(open_questions) == 1
        assert open_questions[0].context["entity_id"] == str(a.id)
        assert open_questions[0].context["candidate_entity_id"] == str(b.id)

    async def test_skips_pair_with_already_open_question(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="r3@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()
        await store.raise_question(
            db_session, user_id, "reconciliation_engine", "¿son la misma entidad?",
            context={"entity_id": str(a.id), "candidate_entity_id": str(b.id)},
            target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        with patch.object(
            reconciliation, "find_candidate_duplicates", AsyncMock(return_value=[(a, b)]),
        ), patch.object(reconciliation, "negotiate_same_as") as mock_negotiate:
            result = await reconciliation.run_reconciliation(db_session, user_id)

        mock_negotiate.assert_not_called()
        assert result["skipped_pending"] == 1
        assert result["negotiated"] == 0
        assert result["escalated"] == 0

    async def test_recomputes_confidence_for_auto_linked_entities(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="r4@example.com")
        a = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "A", attributes={"email": "x@y.com"},
        )
        b = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "B", attributes={"email": "x@y.com"},
        )
        await db_session.commit()

        with patch.object(reconciliation, "find_candidate_duplicates", AsyncMock(return_value=[])):
            result = await reconciliation.run_reconciliation(db_session, user_id)
        await db_session.commit()

        assert result["auto_linked"] == 1
        assert result["entities_recomputed"] == 2
        refetched_a = await store.get_entity(db_session, user_id, a.id)
        assert refetched_a is not None
        # base 0.5 + 0.1 for the one same_as link
        assert refetched_a.confidence == 0.6
