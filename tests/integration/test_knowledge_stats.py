"""Tests for Phase 7 knowledge observability: store.get_knowledge_stats and
GET /knowledge/status.

specs/plan-multi-agent-knowledge.md, Phase 7 — the concrete check that "the
knowledge base gets more solid over time" is a verifiable claim.
"""
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app as fastapi_app

from app.models.entity import EntityType
from app.models.entity_link import LinkResolvedBy
from app.models.pending_question import QuestionTarget
from app.services.agent.knowledge import store
from tests.factories import make_user


async def _make_persisted_user(db: AsyncSession, **kwargs) -> uuid.UUID:
    user = make_user(**kwargs)
    db.add(user)
    await db.commit()
    return user.id


class TestGetKnowledgeStatsStore:
    async def test_empty_knowledge_base_returns_zeros(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ks1@example.com")

        stats = await store.get_knowledge_stats(db_session, user_id)

        assert stats["total_entities"] == 0
        assert stats["entities_by_confidence"] == {"low": 0, "medium": 0, "high": 0}
        assert stats["entities_by_type"] == {}
        assert stats["total_claims"] == 0
        assert stats["pending_questions_open"] == 0
        assert stats["entities_merged_recent"] == 0

    async def test_buckets_entities_by_confidence(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ks2@example.com")
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Low", confidence=0.2)
        await store.create_entity(db_session, user_id, EntityType.PERSON, "Mid", confidence=0.5)
        await store.create_entity(db_session, user_id, EntityType.PROJECT, "High", confidence=0.9)
        await db_session.commit()

        stats = await store.get_knowledge_stats(db_session, user_id)

        assert stats["entities_by_confidence"] == {"low": 1, "medium": 1, "high": 1}
        assert stats["entities_by_type"] == {"person": 2, "project": 1}
        assert stats["total_entities"] == 3

    async def test_counts_claims_by_source_and_status(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ks3@example.com")
        entity = await store.create_entity(db_session, user_id, EntityType.PERSON, "X")
        await db_session.commit()
        await store.add_claim(db_session, entity.id, user_id, "slack", "a", "slack_domain_agent")
        await store.add_claim(db_session, entity.id, user_id, "rd", "b", "rd_domain_agent")
        await db_session.commit()

        stats = await store.get_knowledge_stats(db_session, user_id)

        assert stats["claims_by_source"] == {"slack": 1, "rd": 1}
        assert stats["claims_by_status"] == {"active": 2}
        assert stats["total_claims"] == 2

    async def test_counts_only_open_questions_by_target(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ks4@example.com")
        await store.raise_question(
            db_session, user_id, "slack_domain_agent", "duda pares", target=QuestionTarget.PEER_AGENTS,
        )
        question = await store.raise_question(
            db_session, user_id, "outlook_domain_agent", "duda humano", target=QuestionTarget.HUMAN,
        )
        await db_session.commit()
        from app.models.pending_question import ResolvedBy
        await store.resolve_question(db_session, user_id, question.id, ResolvedBy.HUMAN)
        await db_session.commit()

        stats = await store.get_knowledge_stats(db_session, user_id)

        # The HUMAN question was resolved — only the still-open PEER_AGENTS one counts.
        assert stats["pending_questions_by_target"] == {"peer_agents": 1}
        assert stats["pending_questions_open"] == 1

    async def test_counts_recent_same_as_merges_within_window(self, db_session: AsyncSession) -> None:
        user_id = await _make_persisted_user(db_session, email="ks5@example.com")
        a = await store.create_entity(db_session, user_id, EntityType.PERSON, "A")
        b = await store.create_entity(db_session, user_id, EntityType.PERSON, "B")
        c = await store.create_entity(db_session, user_id, EntityType.PERSON, "C")
        await db_session.commit()
        await store.link_entities(db_session, user_id, a.id, b.id, "same_as", LinkResolvedBy.DETERMINISTIC)
        # A non-merge relation must not be counted as a merge.
        await store.link_entities(db_session, user_id, a.id, c.id, "collaborates_with", LinkResolvedBy.SWARM)
        await db_session.commit()

        stats = await store.get_knowledge_stats(db_session, user_id)
        assert stats["entities_merged_recent"] == 1

        # A window of 0 hours excludes even just-created links.
        stats_zero_window = await store.get_knowledge_stats(db_session, user_id, merged_window_hours=0)
        assert stats_zero_window["entities_merged_recent"] == 0

    async def test_scoped_by_user_id(self, db_session: AsyncSession) -> None:
        user_a = await _make_persisted_user(db_session, email="ks6a@example.com")
        user_b = await _make_persisted_user(db_session, email="ks6b@example.com")
        await store.create_entity(db_session, user_a, EntityType.PERSON, "OnlyA")
        await db_session.commit()

        stats_b = await store.get_knowledge_stats(db_session, user_b)
        assert stats_b["total_entities"] == 0


class TestGetKnowledgeStatusEndpoint:
    async def test_returns_stats_for_current_user(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={"email": "ksapi1@example.com", "full_name": "KS User"})
        user_id = resp.json()["id"]

        resp = await client.get("/knowledge/status", headers={"X-User-Id": user_id})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entities"] == 0
        assert data["merged_window_hours"] == 24

    async def test_accepts_merged_window_hours_query_param(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={"email": "ksapi2@example.com", "full_name": "KS User 2"})
        user_id = resp.json()["id"]

        resp = await client.get(
            "/knowledge/status", params={"merged_window_hours": 72}, headers={"X-User-Id": user_id},
        )

        assert resp.status_code == 200
        assert resp.json()["merged_window_hours"] == 72

    async def test_scheduler_active_false_when_no_scheduler_attached(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={"email": "ksapi3@example.com", "full_name": "KS User 3"})
        user_id = resp.json()["id"]

        resp = await client.get("/knowledge/status", headers={"X-User-Id": user_id})

        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduler_active"] is False
        assert data["next_scheduled_run"] is None

    async def test_reports_scheduler_active_and_next_run_when_job_exists(self, client: AsyncClient) -> None:
        resp = await client.post("/users/", json={"email": "ksapi4@example.com", "full_name": "KS User 4"})
        user_id = resp.json()["id"]

        mock_scheduler = MagicMock()
        mock_scheduler.is_running = True
        mock_scheduler.get_job_info.return_value = [
            {"job_id": f"knowledge_cycle_{user_id}", "next_run": "2026-09-07T00:00:00+00:00"},
        ]
        fastapi_app.state.knowledge_scheduler = mock_scheduler
        try:
            resp = await client.get("/knowledge/status", headers={"X-User-Id": user_id})
        finally:
            del fastapi_app.state.knowledge_scheduler

        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduler_active"] is True
        assert data["next_scheduled_run"] == "2026-09-07T00:00:00+00:00"

    async def test_next_scheduled_run_none_when_job_not_yet_loaded(self, client: AsyncClient) -> None:
        """Scheduler running but this user's job isn't in it yet (e.g. no
        active integration) must not raise — just report no next run."""
        resp = await client.post("/users/", json={"email": "ksapi5@example.com", "full_name": "KS User 5"})
        user_id = resp.json()["id"]

        mock_scheduler = MagicMock()
        mock_scheduler.is_running = True
        mock_scheduler.get_job_info.return_value = []
        fastapi_app.state.knowledge_scheduler = mock_scheduler
        try:
            resp = await client.get("/knowledge/status", headers={"X-User-Id": user_id})
        finally:
            del fastapi_app.state.knowledge_scheduler

        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduler_active"] is True
        assert data["next_scheduled_run"] is None
