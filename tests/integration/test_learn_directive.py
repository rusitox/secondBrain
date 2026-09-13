"""Integration tests for apply_learn_directive — the DB-backed half of
Fase 2's learning loop (app.services.agent.knowledge.answer). See
tests/unit/test_learn_directive.py for the pure claim-template
substitution tests.
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityType
from app.models.entity_claim import EntityClaim
from app.services.agent.knowledge.answer import apply_learn_directive
from tests.factories import make_user


class TestApplyLearnDirective:
    @pytest.mark.asyncio
    async def test_no_learn_key_returns_none(self, db_session: AsyncSession) -> None:
        result = await apply_learn_directive(db_session, uuid.uuid4(), {}, {"decision": "approve"})
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_entity_id_returns_none(self, db_session: AsyncSession) -> None:
        spec = {"learn": {"entity_id": "not-a-uuid", "claim_template": "x"}}
        result = await apply_learn_directive(db_session, uuid.uuid4(), spec, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_directive_writes_a_confirmed_claim(self, db_session: AsyncSession) -> None:
        user = make_user(email=f"learn_{uuid.uuid4().hex[:8]}@test.com")
        db_session.add(user)
        await db_session.flush()

        entity = Entity(
            user_id=user.id, entity_type=EntityType.TOPIC, canonical_name="Presupuesto Q4",
            aliases=[], attributes={}, confidence=0.5,
        )
        db_session.add(entity)
        await db_session.flush()

        spec = {"learn": {"entity_id": str(entity.id), "claim_template": "Decisión: {decision}"}}
        result = await apply_learn_directive(db_session, user.id, spec, {"decision": "approve"})

        assert result is not None
        assert result.get("recorded") is True

        claims = (await db_session.execute(
            select(EntityClaim).where(EntityClaim.entity_id == entity.id)
        )).scalars().all()
        assert len(claims) == 1
        assert claims[0].claim_text == "Decisión: approve"
        assert claims[0].status.value == "confirmed_by_user"
        assert claims[0].source == "user"
