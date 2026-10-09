"""Integration tests for GET /people and GET /people/{entity_id} — the
relationship-intelligence panel. Read-only, composes the existing knowledge
graph (app/services/agent/knowledge/store.py), no LLM involved.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.people import PEOPLE_LIST_LIMIT
from app.models.entity import EntityType
from app.models.entity_link import LinkResolvedBy
from app.services.agent.knowledge import store
from tests.factories import make_user


async def _create_user(client: AsyncClient, email: str) -> str:
    resp = await client.post("/users/", json={"email": email, "full_name": "People User"})
    return resp.json()["id"]


class TestListPeople:
    @pytest.mark.asyncio
    async def test_returns_empty_list_with_no_people(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "people_empty@example.com")

        resp = await client.get("/people", headers={"X-User-Id": user_id})

        assert resp.status_code == 200
        assert resp.json() == {"people": []}

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/people")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_includes_role_when_known_sorted_by_confidence(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"people_list_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.flush()
        low = await store.create_entity(
            db_session, user.id, EntityType.PERSON, "Bajo", confidence=0.3,
        )
        high = await store.create_entity(
            db_session, user.id, EntityType.PERSON, "Alto", confidence=0.9,
        )
        await db_session.commit()
        await store.add_claim(
            db_session, high.id, user.id, "slack", "Head of Product", "slack_domain_agent",
            claim_type="role",
        )
        # Not a PERSON — must never show up in the list.
        await store.create_entity(db_session, user.id, EntityType.PROJECT, "Proyecto X")
        await db_session.commit()

        resp = await client.get("/people", headers={"X-User-Id": str(user.id)})

        assert resp.status_code == 200
        people = resp.json()["people"]
        assert len(people) == 2
        # Sorted by confidence descending.
        assert people[0]["canonical_name"] == "Alto"
        assert people[0]["role"] == "Head of Product"
        assert people[1]["canonical_name"] == "Bajo"
        assert people[1]["role"] is None

    @pytest.mark.asyncio
    async def test_caps_at_people_list_limit_keeping_highest_confidence(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        """Regression: confirmed live against a real account with 1937
        PERSON entities that profiling every one of them (claims + links)
        to list names/roles projected to ~5s and only grows over time —
        same bug class as daily_planning.py's unbounded pending_question
        fetch. Must cap to the top PEOPLE_LIST_LIMIT by confidence, not
        just truncate whatever order the DB happens to return."""
        user = make_user(email=f"people_cap_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.flush()
        for i in range(PEOPLE_LIST_LIMIT + 5):
            await store.create_entity(
                db_session, user.id, EntityType.PERSON, f"Persona {i}", confidence=0.5,
            )
        best = await store.create_entity(
            db_session, user.id, EntityType.PERSON, "La Mas Confiable", confidence=0.99,
        )
        await db_session.commit()

        resp = await client.get("/people", headers={"X-User-Id": str(user.id)})

        assert resp.status_code == 200
        people = resp.json()["people"]
        assert len(people) == PEOPLE_LIST_LIMIT
        assert people[0]["entity_id"] == str(best.id)


class TestGetPerson:
    @pytest.mark.asyncio
    async def test_unknown_entity_returns_404(self, client: AsyncClient) -> None:
        user_id = await _create_user(client, "people_404@example.com")

        resp = await client.get(f"/people/{uuid.uuid4()}", headers={"X-User-Id": user_id})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(f"/people/{uuid.uuid4()}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cannot_see_another_users_entity(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        owner = make_user(email=f"people_owner_{uuid.uuid4().hex[:8]}@test.com")
        other = make_user(email=f"people_other_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add_all([owner, other])
        await db_session.flush()
        entity = await store.create_entity(db_session, owner.id, EntityType.PERSON, "Privado")
        await db_session.commit()

        resp = await client.get(f"/people/{entity.id}", headers={"X-User-Id": str(other.id)})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_claims_grouped_by_type_and_related_entities(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        user = make_user(email=f"people_detail_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.flush()
        person = await store.create_entity(
            db_session, user.id, EntityType.PERSON, "Juan", attributes={"email": "juan@x.com"},
        )
        org = await store.create_entity(db_session, user.id, EntityType.ORGANIZATION, "Acme")
        await db_session.commit()
        await store.add_claim(
            db_session, person.id, user.id, "slack", "Head of Product en Trainly", "slack_domain_agent",
            claim_type="role",
        )
        await store.link_entities(
            db_session, user.id, person.id, org.id,
            relation_type="works_at", resolved_by=LinkResolvedBy.DETERMINISTIC,
        )
        await db_session.commit()

        resp = await client.get(f"/people/{person.id}", headers={"X-User-Id": str(user.id)})

        assert resp.status_code == 200
        body = resp.json()
        assert body["canonical_name"] == "Juan"
        assert body["attributes"] == {"email": "juan@x.com"}
        assert body["claims_by_type"]["role"][0]["claim_text"] == "Head of Product en Trainly"
        assert body["related_entities"] == [
            {"relation_type": "works_at", "entity_id": str(org.id), "canonical_name": "Acme"}
        ]
