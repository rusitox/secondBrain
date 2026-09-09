"""Integration tests for the multi-agent knowledge schema (Phase 0).

Pure data-access round-trips through app/services/agent/knowledge/store.py —
no agent/LLM logic exists yet. See specs/plan-multi-agent-knowledge.md.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityType
from app.models.entity_claim import ClaimStatus
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionStatus, QuestionTarget, ResolvedBy
from app.services.agent.knowledge import store
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


class TestEntityCRUD:
    async def test_create_and_get_entity(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="a@example.com")

        entity = await store.create_entity(
            db_session, user_id, EntityType.PERSON, "Mariano Ortega"
        )
        await db_session.commit()

        fetched = await store.get_entity(db_session, user_id, entity.id)
        assert fetched is not None
        assert fetched.canonical_name == "Mariano Ortega"
        assert fetched.entity_type == EntityType.PERSON
        assert fetched.aliases == []
        assert fetched.attributes == {}
        assert fetched.confidence == 0.5

    async def test_create_entity_with_aliases_and_attributes(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="b@example.com")

        entity = await store.create_entity(
            db_session,
            user_id,
            EntityType.PROJECT,
            "Proyecto Atlas",
            aliases=["Atlas", "El proyecto de Atlas"],
            attributes={"team": "I+D"},
            confidence=0.8,
        )
        await db_session.commit()

        fetched = await store.get_entity(db_session, user_id, entity.id)
        assert fetched is not None
        assert fetched.aliases == ["Atlas", "El proyecto de Atlas"]
        assert fetched.attributes == {"team": "I+D"}
        assert fetched.confidence == 0.8

    async def test_list_entities_filters_by_type(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="c@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Persona 1")
        await store.create_entity(db_session, user_id, EntityType.PROJECT, "Proyecto 1")
        await db_session.commit()

        people = await store.list_entities(db_session, user_id, entity_type=EntityType.PERSON)
        assert len(people) == 1
        assert people[0].canonical_name == "Persona 1"

        everything = await store.list_entities(db_session, user_id)
        assert len(everything) == 2

    async def test_update_entity_confidence(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="d@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()

        updated = await store.update_entity_confidence(db_session, user_id, entity.id, 0.95)
        await db_session.commit()

        assert updated is not None
        assert updated.confidence == 0.95
        refetched = await store.get_entity(db_session, user_id, entity.id)
        assert refetched is not None
        assert refetched.confidence == 0.95

    async def test_update_entity_confidence_missing_entity_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="d2@example.com")
        result = await store.update_entity_confidence(db_session, user_id, uuid.uuid4(), 0.9)
        assert result is None

    async def test_get_entity_does_not_leak_across_users(self, db_session: AsyncSession) -> None:
        owner_id = await _make_persisted_user(db_session, email="owner@example.com")
        other_id = await _make_persisted_user(db_session, email="other@example.com")
        entity = await store.create_entity(db_session, owner_id, EntityType.PERSON, "Secreto")
        await db_session.commit()

        assert await store.get_entity(db_session, other_id, entity.id) is None
        assert await store.get_entity(db_session, owner_id, entity.id) is not None

    async def test_delete_entity_cascades_claims_and_links(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="del1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Borrar")
        other = await store.create_entity(db_session, user_id, EntityType.PERSON, "Otro")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "claim", "slack_domain_agent")
        await store.link_entities(
            db_session, user_id, entity.id, other.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.USER,
        )
        await db_session.commit()

        deleted = await store.delete_entity(db_session, user_id, entity.id)
        await db_session.commit()

        assert deleted is True
        assert await store.get_entity(db_session, user_id, entity.id) is None
        # ON DELETE CASCADE on EntityClaim.entity_id / EntityLink.entity_id_a|b —
        # nothing left dangling on either side of what was just deleted.
        assert await store.list_claims_for_user(db_session, user_id) == []
        assert await store.list_links_for_entity(db_session, user_id, other.id) == []

    async def test_delete_entity_missing_or_other_user_returns_false(
        self, db_session: AsyncSession
    ) -> None:
        owner_id = await _make_persisted_user(db_session, email="del2a@example.com")
        other_id = await _make_persisted_user(db_session, email="del2b@example.com")
        entity = await store.create_entity(db_session, owner_id, EntityType.PERSON, "X")
        await db_session.commit()

        assert await store.delete_entity(db_session, owner_id, uuid.uuid4()) is False
        assert await store.delete_entity(db_session, other_id, entity.id) is False
        assert await store.get_entity(db_session, owner_id, entity.id) is not None

    async def test_find_similar_entities_without_embedding_returns_empty(
        self, db_session: AsyncSession
    ) -> None:
        """Short-circuits before ever issuing the cosine_distance query, which
        needs pgvector (Postgres) — this path is the only part of
        find_similar_entities testable without it."""
        user_id = await _make_persisted_user(db_session, email="sim1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()

        assert entity.embedding is None
        assert await store.find_similar_entities(db_session, user_id, entity) == []


class TestClaimCRUD:
    async def test_add_and_list_claims(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="e@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()

        claim = await store.add_claim(
            db_session,
            entity.id,
            user_id,
            source="slack",
            claim_text="Trabaja en el equipo de plataforma",
            asserted_by_agent="slack_domain_agent",
            source_ref="msg-123",
            confidence=0.7,
        )
        await db_session.commit()

        assert claim.status == ClaimStatus.ACTIVE
        claims = await store.list_claims(db_session, user_id, entity.id)
        assert len(claims) == 1
        assert claims[0].claim_text == "Trabaja en el equipo de plataforma"
        assert claims[0].source == "slack"

    async def test_list_claims_filters_by_status(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="f@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Z")
        await db_session.commit()

        await store.add_claim(
            db_session, entity.id, user_id, "slack", "claim A", "slack_domain_agent",
            status=ClaimStatus.ACTIVE,
        )
        await store.add_claim(
            db_session, entity.id, user_id, "outlook", "claim B", "outlook_domain_agent",
            status=ClaimStatus.DISPUTED,
        )
        await db_session.commit()

        active = await store.list_claims(db_session, user_id, entity.id, status=ClaimStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].claim_text == "claim A"

    async def test_add_claim_rejects_entity_from_another_user(self, db_session: AsyncSession) -> None:
        owner_id = await _make_persisted_user(db_session, email="owner2@example.com")
        other_id = await _make_persisted_user(db_session, email="other2@example.com")
        entity = await store.create_entity(db_session, owner_id, EntityType.PERSON, "X")
        await db_session.commit()

        with pytest.raises(ValueError):
            await store.add_claim(
                db_session, entity.id, other_id, "slack", "claim", "slack_domain_agent",
            )

    async def test_dispute_claim_flips_status(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="disp1@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        claim = await store.add_claim(
            db_session, entity.id, user_id, "slack", "claim equivocado", "slack_domain_agent",
        )
        await db_session.commit()

        disputed = await store.dispute_claim(db_session, user_id, claim.id)
        await db_session.commit()

        assert disputed is not None
        assert disputed.status == ClaimStatus.DISPUTED
        active = await store.list_claims(db_session, user_id, entity.id, status=ClaimStatus.ACTIVE)
        assert active == []

    async def test_dispute_claim_missing_or_other_user_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        owner_id = await _make_persisted_user(db_session, email="disp2a@example.com")
        other_id = await _make_persisted_user(db_session, email="disp2b@example.com")
        entity = await store.create_entity(db_session, owner_id, EntityType.PERSON, "X")
        await db_session.commit()
        claim = await store.add_claim(
            db_session, entity.id, owner_id, "slack", "claim", "slack_domain_agent",
        )
        await db_session.commit()

        assert await store.dispute_claim(db_session, owner_id, uuid.uuid4()) is None
        assert await store.dispute_claim(db_session, other_id, claim.id) is None

    async def test_dispute_claim_scoped_to_entity_id_when_given(self, db_session: AsyncSession) -> None:
        """correct_knowledge always passes entity_id alongside claim_id — a
        claim_id that belongs to a different entity than the one named must
        not be disputed, since that would mean a mismatched conversation
        reference silently corrupts an unrelated entity's claims."""
        user_id = await _make_persisted_user(db_session, email="disp3@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        other_entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "Y")
        await db_session.commit()
        claim = await store.add_claim(
            db_session, entity.id, user_id, "slack", "claim", "slack_domain_agent",
        )
        await db_session.commit()

        assert await store.dispute_claim(db_session, user_id, claim.id, entity_id=other_entity.id) is None
        assert await store.dispute_claim(db_session, user_id, claim.id, entity_id=entity.id) is not None


class TestEntityLinkCRUD:
    async def test_link_entities_and_list_from_either_side(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="g@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "Slack Juan")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "Outlook Juan")
        await db_session.commit()

        link = await store.link_entities(
            db_session, user_id, entity_a.id, entity_b.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.SWARM, confidence=0.85,
        )
        await db_session.commit()

        assert link.relation_type == "same_as"
        links_from_a = await store.list_links_for_entity(db_session, user_id, entity_a.id)
        links_from_b = await store.list_links_for_entity(db_session, user_id, entity_b.id)
        assert len(links_from_a) == 1
        assert len(links_from_b) == 1
        assert links_from_a[0].id == links_from_b[0].id

    async def test_links_exist_either_ordering(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="le1@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await db_session.commit()

        assert await store.links_exist(db_session, user_id, entity_a.id, entity_b.id) is False

        await store.link_entities(
            db_session, user_id, entity_a.id, entity_b.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.USER,
        )
        await db_session.commit()

        assert await store.links_exist(db_session, user_id, entity_a.id, entity_b.id) is True
        # Order-independent — a correct_knowledge call naming the entities in
        # the other order must still find the existing link.
        assert await store.links_exist(db_session, user_id, entity_b.id, entity_a.id) is True
        assert await store.links_exist(db_session, user_id, entity_a.id, entity_b.id, relation_type="other") is False

    async def test_unlink_entities_removes_either_ordering(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="un1@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await db_session.commit()
        await store.link_entities(
            db_session, user_id, entity_a.id, entity_b.id,
            relation_type="same_as", resolved_by=LinkResolvedBy.SWARM,
        )
        await db_session.commit()

        # Named in the opposite order from how the link was created.
        removed = await store.unlink_entities(db_session, user_id, entity_b.id, entity_a.id)
        await db_session.commit()

        assert removed == 1
        assert await store.list_links_for_entity(db_session, user_id, entity_a.id) == []

    async def test_unlink_entities_no_match_returns_zero(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="un2@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await db_session.commit()

        assert await store.unlink_entities(db_session, user_id, entity_a.id, entity_b.id) == 0


class TestPendingQuestionLifecycle:
    async def test_raise_question_defaults_to_peer_agents(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="h@example.com")

        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent",
            "¿El 'Juan' de este mensaje es el mismo que aparece en Outlook?",
        )
        await db_session.commit()

        assert question.target == QuestionTarget.PEER_AGENTS
        assert question.status == QuestionStatus.OPEN
        assert question.candidate_answer is None

    async def test_escalate_to_human_carries_candidate_answer(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="i@example.com")
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Es la misma persona?",
        )
        await db_session.commit()

        escalated = await store.escalate_to_human(
            db_session, user_id, question.id,
            candidate_answer="Creemos que sí, por coincidencia de email",
            candidate_confidence=0.6,
        )
        await db_session.commit()

        assert escalated is not None
        assert escalated.target == QuestionTarget.HUMAN
        assert escalated.candidate_answer == "Creemos que sí, por coincidencia de email"
        assert escalated.candidate_confidence == 0.6

    async def test_escalate_to_human_missing_question_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        user_id = await _make_persisted_user(db_session, email="i2@example.com")
        result = await store.escalate_to_human(db_session, user_id, uuid.uuid4())
        assert result is None

    async def test_escalate_to_human_does_not_leak_across_users(self, db_session: AsyncSession) -> None:
        owner_id = await _make_persisted_user(db_session, email="owner3@example.com")
        other_id = await _make_persisted_user(db_session, email="other3@example.com")
        question = await store.raise_question(db_session, owner_id, "slack_domain_agent", "duda")
        await db_session.commit()

        assert await store.escalate_to_human(db_session, other_id, question.id) is None

    async def test_resolve_question(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="j@example.com")
        question = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "¿Es la misma persona?",
        )
        await db_session.commit()

        resolved = await store.resolve_question(
            db_session, user_id, question.id, ResolvedBy.PEER_SWARM,
            answer_text="Sí, confirmado por email",
        )
        await db_session.commit()

        assert resolved is not None
        assert resolved.status == QuestionStatus.ANSWERED
        assert resolved.resolved_by == ResolvedBy.PEER_SWARM
        assert resolved.answer_text == "Sí, confirmado por email"
        assert resolved.answered_at is not None

    async def test_list_open_questions_excludes_resolved(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="k@example.com")
        q1 = await store.raise_question(db_session, user_id, "slack_domain_agent", "duda 1")
        q2 = await store.raise_question(db_session, user_id, "outlook_domain_agent", "duda 2")
        await db_session.commit()
        await store.resolve_question(db_session, user_id, q1.id, ResolvedBy.KNOWLEDGE_BASE)
        await db_session.commit()

        open_questions = await store.list_open_questions(db_session, user_id)
        assert len(open_questions) == 1
        assert open_questions[0].id == q2.id

    async def test_list_open_questions_filters_by_target(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="l@example.com")
        await store.raise_question(
            db_session, user_id, "slack_domain_agent", "duda para pares",
            target=QuestionTarget.PEER_AGENTS,
        )
        await store.raise_question(
            db_session, user_id, "outlook_domain_agent", "duda para humano",
            target=QuestionTarget.HUMAN, candidate_answer="palpito",
        )
        await db_session.commit()

        human_questions = await store.list_open_questions(
            db_session, user_id, target=QuestionTarget.HUMAN
        )
        assert len(human_questions) == 1
        assert human_questions[0].question_text == "duda para humano"


class TestListEntitiesSearchAndPagination:
    """Phase 4 (specs/plan-knowledge-backoffice.md) additions to list_entities."""

    async def test_search_matches_case_insensitive_substring(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="m1@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Mariano Ortega")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Juan Perez")
        await db_session.commit()

        results = await store.list_entities(db_session, user_id, search="mariano")
        assert [e.canonical_name for e in results] == ["Mariano Ortega"]

    async def test_min_confidence_filters_out_lower(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="m2@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Low", confidence=0.2)
        await store.create_entity(db_session, user_id, EntityType.PERSON, "High", confidence=0.9)
        await db_session.commit()

        results = await store.list_entities(db_session, user_id, min_confidence=0.5)
        assert [e.canonical_name for e in results] == ["High"]

    async def test_limit_and_offset_paginate(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="m3@example.com")
        for name in ("A", "B", "C"):
            await store.create_entity(db_session, user_id, EntityType.PERSON, name)
        await db_session.commit()

        first_page = await store.list_entities(db_session, user_id, limit=2, offset=0)
        second_page = await store.list_entities(db_session, user_id, limit=2, offset=2)
        assert [e.canonical_name for e in first_page] == ["A", "B"]
        assert [e.canonical_name for e in second_page] == ["C"]

    async def test_count_entities_matches_filters(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="m4@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        await store.create_entity(db_session, user_id, EntityType.PROJECT, "B")
        await db_session.commit()

        assert await store.count_entities(db_session, user_id) == 2
        assert await store.count_entities(db_session, user_id, entity_type=EntityType.PROJECT) == 1

    async def test_scoped_by_user(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="m5a@example.com")
        user_b = await _make_persisted_user(db_session, email="m5b@example.com")
        await store.create_entity(db_session, user_a, EntityType.PERSON, "A")
        await db_session.commit()

        assert await store.list_entities(db_session, user_b, search="a") == []


class TestListClaimsForUser:
    async def test_lists_across_entities_scoped_by_user(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="n1@example.com")
        entity_a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        entity_b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        await db_session.commit()
        await store.add_claim(db_session, entity_a.id, user_id, "slack", "claim1", "slack_domain_agent")
        await store.add_claim(db_session, entity_b.id, user_id, "outlook", "claim2", "outlook_domain_agent")
        await db_session.commit()

        claims = await store.list_claims_for_user(db_session, user_id)
        assert {c.claim_text for c in claims} == {"claim1", "claim2"}

    async def test_filters_by_source_and_status(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="n2@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        await db_session.commit()
        await store.add_claim(
            db_session, entity.id, user_id, "slack", "active claim", "slack_domain_agent",
            status=ClaimStatus.ACTIVE,
        )
        await store.add_claim(
            db_session, entity.id, user_id, "outlook", "disputed claim", "outlook_domain_agent",
            status=ClaimStatus.DISPUTED,
        )
        await db_session.commit()

        slack_only = await store.list_claims_for_user(db_session, user_id, source="slack")
        assert [c.claim_text for c in slack_only] == ["active claim"]

        active_only = await store.list_claims_for_user(db_session, user_id, status=ClaimStatus.ACTIVE)
        assert [c.claim_text for c in active_only] == ["active claim"]


class TestListQuestions:
    async def test_returns_any_status_unlike_list_open_questions(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="o1@example.com")
        open_q = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "open", target=QuestionTarget.HUMAN,
        )
        answered_q = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "answered", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()
        await store.resolve_question(db_session, user_id, answered_q.id, resolved_by=ResolvedBy.HUMAN)
        await db_session.commit()

        all_questions = await store.list_questions(db_session, user_id)
        assert {q.id for q in all_questions} == {open_q.id, answered_q.id}

        open_only = await store.list_questions(db_session, user_id, status=QuestionStatus.OPEN)
        assert [q.id for q in open_only] == [open_q.id]

    async def test_count_questions_matches_filters_regardless_of_limit(
        self, db_session: AsyncSession,
    ) -> None:
        """The backoffice's X-Total-Count header depends on this being the
        real filtered count, not bounded by whatever `limit` list_questions'
        page used — otherwise the UI undercounts past that page size."""
        user_id = await _make_persisted_user(db_session, email="o3@example.com")
        open_q = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "open", target=QuestionTarget.HUMAN,
        )
        answered_q = await store.raise_question(
            db_session, user_id, "slack_domain_agent", "answered", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()
        await store.resolve_question(db_session, user_id, answered_q.id, resolved_by=ResolvedBy.HUMAN)
        await db_session.commit()

        assert await store.count_questions(db_session, user_id) == 2
        assert await store.count_questions(db_session, user_id, status=QuestionStatus.OPEN) == 1
        # A one-row page must not cap the count — the whole point of this function.
        page = await store.list_questions(db_session, user_id, status=QuestionStatus.OPEN, limit=1)
        assert len(page) == 1
        assert page[0].id == open_q.id

    async def test_scoped_by_user(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="o2a@example.com")
        user_b = await _make_persisted_user(db_session, email="o2b@example.com")
        await store.raise_question(
            db_session, user_a, "slack_domain_agent", "q", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()

        assert await store.list_questions(db_session, user_b) == []
