"""Unit tests for find_candidate_duplicates' pairing/dedup logic.

store.find_similar_entities needs pgvector (Postgres) and can't run against
the SQLite test DB — see tests/integration/test_reconciliation.py for
everything else, which runs against a real (SQLite) DB. Here the store layer
is mocked so this file tests only reconciliation.py's own logic: dedup a
pair regardless of which side's similarity search surfaced it, skip already-
linked pairs, and never compare an entity against itself.
"""
import uuid
from unittest.mock import AsyncMock, patch

from app.models.entity import Entity, EntityType
from app.services.agent.knowledge import reconciliation


def _make_entity(entity_type: EntityType = EntityType.PERSON) -> Entity:
    e = Entity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        entity_type=entity_type,
        canonical_name="X",
        aliases=[],
        attributes={},
        confidence=0.5,
    )
    return e


class TestFindCandidateDuplicates:
    async def test_pair_returned_once_regardless_of_which_side_surfaced_it(self) -> None:
        a, b = _make_entity(), _make_entity()

        async def fake_list_entities(db, user_id, entity_type=None):
            return [a, b]

        async def fake_find_similar(db, user_id, entity, max_distance=0.15, limit=5):
            # Symmetric similarity: each entity's search surfaces the other.
            return [b] if entity is a else [a]

        with patch.object(reconciliation.store, "list_entities", fake_list_entities), \
             patch.object(reconciliation.store, "find_similar_entities", fake_find_similar), \
             patch.object(reconciliation, "_already_linked", AsyncMock(return_value=False)):
            candidates = await reconciliation.find_candidate_duplicates(
                None, uuid.uuid4(), entity_type=EntityType.PERSON,
            )

        assert len(candidates) == 1
        assert {candidates[0][0].id, candidates[0][1].id} == {a.id, b.id}

    async def test_already_linked_pairs_are_excluded(self) -> None:
        a, b = _make_entity(), _make_entity()

        async def fake_list_entities(db, user_id, entity_type=None):
            return [a, b]

        async def fake_find_similar(db, user_id, entity, max_distance=0.15, limit=5):
            return [b] if entity is a else [a]

        with patch.object(reconciliation.store, "list_entities", fake_list_entities), \
             patch.object(reconciliation.store, "find_similar_entities", fake_find_similar), \
             patch.object(reconciliation, "_already_linked", AsyncMock(return_value=True)):
            candidates = await reconciliation.find_candidate_duplicates(
                None, uuid.uuid4(), entity_type=EntityType.PERSON,
            )

        assert candidates == []

    async def test_no_similar_entities_returns_empty(self) -> None:
        a = _make_entity()

        async def fake_list_entities(db, user_id, entity_type=None):
            return [a]

        async def fake_find_similar(db, user_id, entity, max_distance=0.15, limit=5):
            return []

        with patch.object(reconciliation.store, "list_entities", fake_list_entities), \
             patch.object(reconciliation.store, "find_similar_entities", fake_find_similar):
            candidates = await reconciliation.find_candidate_duplicates(
                None, uuid.uuid4(), entity_type=EntityType.PERSON,
            )

        assert candidates == []

    async def test_defaults_to_scanning_all_entity_types_when_unspecified(self) -> None:
        seen_types = []

        async def fake_list_entities(db, user_id, entity_type=None):
            seen_types.append(entity_type)
            return []

        with patch.object(reconciliation.store, "list_entities", fake_list_entities), \
             patch.object(reconciliation.store, "find_similar_entities", AsyncMock(return_value=[])):
            await reconciliation.find_candidate_duplicates(None, uuid.uuid4())

        assert set(seen_types) == set(EntityType)
