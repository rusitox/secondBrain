"""Sync-status tool — returns last sync timestamps per platform."""
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration


class SyncStatusTool:
    """Returns the last sync timestamp and status for each connected platform."""

    async def get_status(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """Return a list of {platform, last_sync_at, status, error} for all integrations."""
        stmt = (
            select(Integration)
            .where(Integration.user_id == user_id, Integration.is_active.is_(True))
            .order_by(Integration.platform)
        )
        rows = (await db.execute(stmt)).scalars().all()

        results: List[Dict[str, Any]] = []
        for integ in rows:
            last_sync: Optional[str] = None
            if integ.last_sync_at is not None:
                last_sync = integ.last_sync_at.isoformat()
            results.append({
                "platform": integ.platform.value,
                "last_sync_at": last_sync,
                "status": integ.last_sync_status,
                "error": integ.last_sync_error,
                "sync_enabled": integ.sync_enabled,
                "sync_interval_minutes": integ.sync_interval_minutes,
            })

        return results
