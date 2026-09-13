"""Mentions tool — exact-match "where was I @-mentioned" retrieval.

Pure semantic search can't answer this reliably: a mention is stored as a
resolved "@DisplayName" in the document's content (see
app.services.connectors.slack._resolve_mentions) for keyword/semantic
search to have a chance at all, but a display name alone doesn't
disambiguate "mentions of me" from "mentions of someone with a similar
name" — the message's own metadata["mentions"] list of raw Slack user ids
is the only reliable signal, and it needs an exact filter, not similarity.
"""
import logging
import uuid
from typing import Any, Dict, List

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.integration import Integration, Platform

logger = logging.getLogger(__name__)


class MentionsTool:
    """Finds Slack messages that @-mention the current user."""

    name: str = "mentions"
    description: str = (
        "Find Slack messages that @-mention the user, most recent first. "
        "Exact match on the user's own Slack account, not semantic "
        "similarity — use this instead of search_memory for 'mentions of "
        "me' questions."
    )

    async def get_my_mentions(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return Slack messages mentioning the user, newest first.

        Returns an empty list (with a server-side warning logged) if the
        Slack integration hasn't captured the account's own Slack user id
        yet — that's populated lazily by the sync scheduler
        (BaseConnector.get_own_account_id), so a very recently connected
        or never-synced-since-this-feature integration won't have it yet.
        """
        own_id = await self._get_own_slack_id(db, user_id)
        if own_id is None:
            logger.warning(
                "Mentions: no external_account_id for user=%s's Slack integration "
                "— can't match mentions yet (needs a sync to populate it)",
                user_id,
            )
            return []

        stmt = select(Document).where(
            and_(Document.user_id == user_id, Document.source == "slack")
        )
        result = await db.execute(stmt)
        docs = result.scalars().all()

        mentions: List[Dict[str, Any]] = []
        for doc in docs:
            meta = doc.metadata_ or {}
            if own_id not in (meta.get("mentions") or []):
                continue
            mentions.append({
                "author": meta.get("author", ""),
                "channel": meta.get("channel", ""),
                "timestamp": meta.get("timestamp", ""),
                "content": doc.content[:500],
            })

        mentions.sort(key=lambda m: m["timestamp"], reverse=True)
        return mentions[:top_k]

    @staticmethod
    async def _get_own_slack_id(db: AsyncSession, user_id: uuid.UUID) -> Any:
        result = await db.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == user_id,
                    Integration.platform == Platform.SLACK,
                    Integration.is_active == True,  # noqa: E712
                )
            )
        )
        integration = result.scalars().first()
        return integration.external_account_id if integration else None
