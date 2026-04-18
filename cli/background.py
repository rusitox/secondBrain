"""Background sync — periodic platform synchronization during chat."""
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig

logger = logging.getLogger(__name__)

# Default sync interval in minutes
DEFAULT_SYNC_INTERVAL = 30


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
        """Sync all connected platforms."""
        platforms = self._config.platforms_connected
        if not platforms:
            return

        for platform in platforms:
            try:
                result = await self._api.sync_platform(platform)
                if result.get("commitments_detected", 0) > 0 or result.get("documents_created", 0) > 0:
                    self._on_sync_result(platform, result)
            except APIError as e:
                logger.warning("Background sync failed for %s: %s", platform, e.detail)
            except Exception:
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
            except (APIError, Exception):
                logger.exception("Notion commitment sync failed")
