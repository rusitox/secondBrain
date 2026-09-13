"""Backfill Slack mention resolution for already-ingested messages.

app.services.connectors.slack now resolves "<@UID>" mention tokens to
"@DisplayName" in a message's content and extracts a metadata["mentions"]
list of raw ids at ingestion time — but that only applies going forward.
Slack message content is stored verbatim, so documents ingested before
this fix still have the raw, unresolved "<@UID>" token sitting in their
content and no "mentions" metadata at all; without this backfill, nothing
ingested before the fix is findable via get_my_mentions. This script
re-processes those documents in place, reusing SlackConnector's own
resolution methods so the two never drift apart.

NOTE: USER_ID is hardcoded for a single-user self-hosted deployment.

Usage:
  python scripts/backfill_slack_mentions.py [--dry-run]
"""
import asyncio
import logging
import os
import pathlib
import sys
import uuid
from typing import Dict, Set

# Suppress SQLAlchemy echo before engine is created.
os.environ["DEBUG"] = "false"
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Anchor sys.path to the repo root regardless of cwd.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

import httpx
from sqlalchemy import and_, select

from app.core.database import get_session_factory
from app.models.document import Document
from app.models.integration import Integration, Platform
from app.services import integration_service
from app.services.connectors.slack import _MENTION_RE, SlackConnector

USER_ID = uuid.UUID("889ff4f4-b782-4e9f-bfb1-e310ae132827")


async def backfill(dry_run: bool) -> None:
    sf = get_session_factory()
    async with sf() as db:
        integ_result = await db.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == USER_ID,
                    Integration.platform == Platform.SLACK,
                    Integration.is_active == True,  # noqa: E712
                )
            )
        )
        integration = integ_result.scalars().first()
        if integration is None:
            print("No active Slack integration for this user — nothing to backfill.")
            return

        token = integration_service.get_decrypted_token(integration)

        docs_result = await db.execute(
            select(Document).where(
                and_(Document.user_id == USER_ID, Document.source == "slack")
            )
        )
        docs = docs_result.scalars().all()

        # Resolve every mentioned id across all documents in one batch,
        # instead of once per document.
        all_mention_ids: Set[str] = set()
        for doc in docs:
            all_mention_ids.update(_MENTION_RE.findall(doc.content))

        connector = SlackConnector()
        name_map: Dict[str, str] = {}
        if all_mention_ids:
            async with httpx.AsyncClient(timeout=30.0) as client:
                name_map = await connector._resolve_usernames(
                    client, {"Authorization": f"Bearer {token}"}, all_mention_ids,
                )

        updated = 0
        for doc in docs:
            if not _MENTION_RE.search(doc.content):
                continue
            resolved_content, mentions = connector._resolve_mentions(doc.content, name_map)
            print(f"  {doc.id} — {len(mentions)} mention(s)")
            if not dry_run:
                doc.content = resolved_content
                meta = dict(doc.metadata_ or {})
                meta["mentions"] = mentions
                doc.metadata_ = meta
            updated += 1

        if not dry_run:
            await db.commit()

        print(f"\nDone. documents_with_mentions={updated} dry_run={dry_run}")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    asyncio.run(backfill(dry_run))


if __name__ == "__main__":
    main()
