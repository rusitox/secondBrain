"""Fathom connector for meeting transcripts.

NOTE: Fathom has no public REST API (api.fathom.video is NXDOMAIN).
Automatic sync is not possible via HTTP. Use the MCP-based incremental
sync script instead:

    scripts/sync_fathom_incremental.py

Workflow from a Claude Code session:
  1. python scripts/sync_fathom_incremental.py --check
     → prints last_sync_at so Claude knows which meetings to fetch via MCP

  2. Claude calls list_meetings(created_after=<date>) and get_meeting_transcript
     for each new meeting, building a JSON array.

  3. echo '[{...}]' | python scripts/sync_fathom_incremental.py --ingest
     → ingests meetings, updates last_sync_at in the integrations table.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)


class FathomConnector(BaseConnector):
    """Connector for Fathom meeting transcripts.

    Fathom does not expose a public REST API. This connector cannot be used
    for automatic server-side sync. Use scripts/sync_fathom_incremental.py
    from a Claude Code session instead.
    """

    @property
    def platform(self) -> str:
        return "fathom"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
        **kwargs: Any,
    ) -> List[ConnectorItem]:
        """Not available — Fathom has no public REST API.

        Use scripts/sync_fathom_incremental.py from a Claude Code session,
        which accesses Fathom transcripts via the Fathom MCP integration.
        """
        raise NotImplementedError(
            "Fathom has no public REST API (api.fathom.video does not exist). "
            "Run `python scripts/sync_fathom_incremental.py --check` from a "
            "Claude Code session to trigger an MCP-based incremental sync."
        )

    async def validate_token(self, access_token: str) -> bool:
        """Not available — Fathom has no public REST API."""
        raise NotImplementedError(
            "Fathom has no public REST API. Token validation is not supported. "
            "Use scripts/sync_fathom_incremental.py from a Claude Code session."
        )
