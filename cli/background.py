"""Background sync — periodic platform synchronization during chat."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig

logger = logging.getLogger(__name__)

# Default sync interval in minutes
DEFAULT_SYNC_INTERVAL = 30

# Friday = 4 in weekday(), digest triggers after 17:00 local time
_DIGEST_WEEKDAY = 4
_DIGEST_HOUR = 17


class BackgroundSync:
    """Runs periodic platform syncs in a background asyncio task."""

    def __init__(
        self,
        api: APIClient,
        config: CLIConfig,
        on_sync_result: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        self._api = api
        self._config = config
        self._on_sync_result = on_sync_result
        self._task = None  # type: Optional[asyncio.Task]
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the background sync loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        """Stop the background sync loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        """Periodic sync loop."""
        interval_min = self._config.preferences.get(
            "sync_interval", DEFAULT_SYNC_INTERVAL
        )
        interval_sec = max(interval_min * 60, 60)  # minimum 1 minute

        try:
            while self._running:
                await asyncio.sleep(interval_sec)
                if not self._running:
                    break
                await self._sync_all()
        except asyncio.CancelledError:
            return

    async def _sync_all(self) -> None:
        """Sync all connected platforms and Notion integrations."""
        platforms = self._config.platforms_connected

        for platform in platforms:
            try:
                result = await self._api.sync_platform(platform)
                if result.get("commitments_detected", 0) > 0 or result.get("documents_created", 0) > 0:
                    self._on_sync_result(platform, result)
            except APIError as e:
                logger.warning("Background sync failed for %s: %s", platform, e.detail)
            except (httpx.HTTPError, RuntimeError, OSError):
                logger.exception("Unexpected error in background sync for %s", platform)

        # Notion commitment sync (if enabled)
        notion_cfg = self._config.notion
        if notion_cfg and notion_cfg.get("enabled") and notion_cfg.get("commitments_db_id"):
            try:
                result = await self._api.sync_notion_commitments(
                    workspace_config=notion_cfg,
                )
                created = result.get("created_in_notion", 0)
                if created > 0:
                    self._on_sync_result("notion", {
                        "commitments_synced": created,
                    })
                logger.info("Background Notion commitment sync completed")
            except APIError as e:
                logger.warning("Notion commitment sync failed: %s", e.detail)
            except (httpx.HTTPError, RuntimeError):
                logger.exception("Notion commitment sync failed")

        # Weekly digest auto-publish (Friday after 17:00 user-local time)
        await self._maybe_publish_digest()

    async def _maybe_publish_digest(self) -> None:
        """Publish weekly digest if it's Friday after 17:00 UTC and not yet done this week."""
        notion_cfg = self._config.notion
        if not notion_cfg or not notion_cfg.get("enabled"):
            return
        if not notion_cfg.get("briefings_db_id"):
            return

        now = datetime.now(timezone.utc)

        if now.weekday() != _DIGEST_WEEKDAY:
            return
        if now.hour < _DIGEST_HOUR:
            return

        # Dedup key: Monday date of this week (avoids year-boundary issues with %W)
        from datetime import timedelta
        monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        last_digest_week = notion_cfg.get("last_digest_week", "")
        if last_digest_week == monday:
            return

        # Publish digest
        try:
            result = await self._api.publish_digest_to_notion(
                workspace_config=notion_cfg,
            )
            url = result.get("url", "")
            logger.info("Auto-published weekly digest: %s", url)
            self._on_sync_result("digest", {
                "url": url,
                "week": monday,
            })

            # Mark as done for this week
            notion_cfg["last_digest_week"] = monday
            self._config.save()
        except APIError as e:
            logger.warning("Auto digest publish failed: %s", e.detail)
        except (httpx.HTTPError, RuntimeError):
            logger.exception("Auto digest publish failed")
