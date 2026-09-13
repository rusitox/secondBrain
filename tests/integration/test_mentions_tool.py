"""Integration tests for MentionsTool — exact-match "mentions of me"
retrieval, the counterpart to the recency fix in memory_retriever.py:
pure semantic search can't answer this reliably at all (see
app.services.connectors.slack's mention-resolution docstring)."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration, Platform
from app.services.agent.tools.mentions import MentionsTool
from tests.factories import make_document, make_user


async def _make_slack_integration(
    db_session: AsyncSession, user_id, external_account_id=None,
) -> Integration:
    integ = Integration(
        user_id=user_id,
        platform=Platform.SLACK,
        access_token="xoxb-test",
        external_account_id=external_account_id,
    )
    db_session.add(integ)
    await db_session.flush()
    return integ


class TestMentionsTool:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_slack_integration(
        self, db_session: AsyncSession,
    ) -> None:
        tool = MentionsTool()
        user = make_user()
        db_session.add(user)
        await db_session.commit()

        assert await tool.get_my_mentions(db_session, user.id) == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_own_id_not_yet_captured(
        self, db_session: AsyncSession,
    ) -> None:
        """external_account_id is populated lazily by the sync scheduler —
        an integration synced before that fix shipped won't have it yet."""
        tool = MentionsTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        await _make_slack_integration(db_session, user.id, external_account_id=None)
        await db_session.commit()

        assert await tool.get_my_mentions(db_session, user.id) == []

    @pytest.mark.asyncio
    async def test_finds_message_mentioning_the_user(self, db_session: AsyncSession) -> None:
        tool = MentionsTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        await _make_slack_integration(db_session, user.id, external_account_id="U_ME")
        db_session.add(make_document(
            user_id=user.id,
            content="hey @Mariano can you review this?",
            source="slack",
            metadata_={
                "type": "message",
                "author": "Alice",
                "channel": "general",
                "timestamp": "1700000000.000",
                "mentions": ["U_ME"],
            },
        ))
        await db_session.commit()

        mentions = await tool.get_my_mentions(db_session, user.id)
        assert len(mentions) == 1
        assert mentions[0]["author"] == "Alice"
        assert mentions[0]["channel"] == "general"

    @pytest.mark.asyncio
    async def test_excludes_messages_mentioning_someone_else(
        self, db_session: AsyncSession,
    ) -> None:
        tool = MentionsTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        await _make_slack_integration(db_session, user.id, external_account_id="U_ME")
        db_session.add(make_document(
            user_id=user.id,
            content="hey @Daniel can you review this?",
            source="slack",
            metadata_={
                "type": "message", "author": "Alice", "channel": "general",
                "timestamp": "1700000000.000", "mentions": ["U_DANIEL"],
            },
        ))
        await db_session.commit()

        assert await tool.get_my_mentions(db_session, user.id) == []

    @pytest.mark.asyncio
    async def test_sorted_newest_first_and_capped_at_top_k(
        self, db_session: AsyncSession,
    ) -> None:
        tool = MentionsTool()
        user = make_user()
        db_session.add(user)
        await db_session.flush()
        await _make_slack_integration(db_session, user.id, external_account_id="U_ME")
        for i, ts in enumerate(["100.0", "300.0", "200.0"]):
            db_session.add(make_document(
                user_id=user.id,
                content=f"msg {i}",
                source="slack",
                metadata_={
                    "type": "message", "author": "Alice", "channel": "general",
                    "timestamp": ts, "mentions": ["U_ME"],
                },
            ))
        await db_session.commit()

        mentions = await tool.get_my_mentions(db_session, user.id, top_k=2)
        assert [m["timestamp"] for m in mentions] == ["300.0", "200.0"]
