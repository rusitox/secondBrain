"""Unit tests for background sync."""
import asyncio
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cli.api_client import APIClient, APIError
from cli.background import BackgroundSync, _DIGEST_WEEKDAY, _DIGEST_HOUR
from cli.config import CLIConfig


def _make_config(**overrides) -> CLIConfig:
    defaults = dict(
        server_url="http://test:8000",
        user_id="user-123",
        platforms_connected=["slack", "outlook"],
        preferences={"sync_interval": 1},  # 1 minute for testing
    )
    defaults.update(overrides)
    config = CLIConfig(**defaults)
    config.save = MagicMock()
    return config


def _make_api() -> APIClient:
    api = MagicMock(spec=APIClient)
    api.sync_platform = AsyncMock(return_value={
        "documents_created": 3,
        "documents_updated": 1,
        "commitments_detected": 1,
    })
    return api


class TestBackgroundSyncStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        callback = MagicMock()
        bg = BackgroundSync(api=_make_api(), config=_make_config(), on_sync_result=callback)
        await bg.start()
        assert bg.is_running is True
        await bg.stop()
        assert bg.is_running is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self) -> None:
        callback = MagicMock()
        bg = BackgroundSync(api=_make_api(), config=_make_config(), on_sync_result=callback)
        # Should not raise
        await bg.stop()
        assert bg.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        callback = MagicMock()
        bg = BackgroundSync(api=_make_api(), config=_make_config(), on_sync_result=callback)
        await bg.start()
        await bg.start()  # Should not create a second task
        assert bg.is_running is True
        await bg.stop()


class TestBackgroundSyncAll:
    @pytest.mark.asyncio
    async def test_sync_all_calls_api(self) -> None:
        api = _make_api()
        callback = MagicMock()
        config = _make_config(platforms_connected=["slack", "outlook"])
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)

        await bg._sync_all()

        assert api.sync_platform.await_count == 2
        api.sync_platform.assert_any_await("slack")
        api.sync_platform.assert_any_await("outlook")

    @pytest.mark.asyncio
    async def test_sync_all_calls_callback_on_results(self) -> None:
        api = _make_api()
        callback = MagicMock()
        bg = BackgroundSync(
            api=api, config=_make_config(platforms_connected=["slack"]),
            on_sync_result=callback,
        )

        await bg._sync_all()

        callback.assert_called_once_with("slack", {
            "documents_created": 3,
            "documents_updated": 1,
            "commitments_detected": 1,
        })

    @pytest.mark.asyncio
    async def test_sync_all_no_callback_when_zero_results(self) -> None:
        api = _make_api()
        api.sync_platform = AsyncMock(return_value={
            "documents_created": 0, "documents_updated": 0, "commitments_detected": 0,
        })
        callback = MagicMock()
        bg = BackgroundSync(
            api=api, config=_make_config(platforms_connected=["slack"]),
            on_sync_result=callback,
        )

        await bg._sync_all()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_all_no_platforms(self) -> None:
        api = _make_api()
        callback = MagicMock()
        bg = BackgroundSync(
            api=api, config=_make_config(platforms_connected=[]),
            on_sync_result=callback,
        )

        await bg._sync_all()

        api.sync_platform.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_failure_continues(self) -> None:
        api = _make_api()
        api.sync_platform = AsyncMock(side_effect=[
            APIError(500, "Failed"),
            {"documents_created": 2, "documents_updated": 0, "commitments_detected": 0},
        ])
        callback = MagicMock()
        bg = BackgroundSync(
            api=api, config=_make_config(platforms_connected=["slack", "outlook"]),
            on_sync_result=callback,
        )

        await bg._sync_all()

        assert api.sync_platform.await_count == 2  # Both called despite first failing


class TestNotionCommitmentSync:
    @pytest.mark.asyncio
    async def test_notion_sync_called_when_enabled(self) -> None:
        api = _make_api()
        api.sync_notion_commitments = AsyncMock(return_value={
            "created_in_notion": 2, "updated_in_notion": 0,
            "updated_locally": 0, "errors": [],
        })
        api.publish_digest_to_notion = AsyncMock()
        callback = MagicMock()
        config = _make_config(
            platforms_connected=[],
            notion={"enabled": True, "commitments_db_id": "db-123"},
        )
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)
        await bg._sync_all()

        api.sync_notion_commitments.assert_awaited_once()
        callback.assert_any_call("notion", {"commitments_synced": 2})

    @pytest.mark.asyncio
    async def test_notion_sync_skipped_when_disabled(self) -> None:
        api = _make_api()
        api.sync_notion_commitments = AsyncMock()
        callback = MagicMock()
        config = _make_config(platforms_connected=[], notion=None)
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)
        await bg._sync_all()

        api.sync_notion_commitments.assert_not_awaited()


class TestDigestAutoPublish:
    @pytest.mark.asyncio
    async def test_digest_published_on_friday_after_17(self) -> None:
        api = _make_api()
        api.publish_digest_to_notion = AsyncMock(return_value={
            "url": "https://notion.so/digest",
        })
        callback = MagicMock()
        notion_cfg = {"enabled": True, "briefings_db_id": "db-123"}
        config = _make_config(platforms_connected=[], notion=notion_cfg)
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)

        # Mock datetime to Friday 18:00 UTC
        friday_18 = datetime(2026, 4, 17, 18, 0, tzinfo=timezone.utc)
        assert friday_18.weekday() == _DIGEST_WEEKDAY

        with patch("cli.background.datetime") as mock_dt:
            mock_dt.now.return_value = friday_18
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await bg._maybe_publish_digest()

        api.publish_digest_to_notion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_digest_not_published_on_thursday(self) -> None:
        api = _make_api()
        api.publish_digest_to_notion = AsyncMock()
        callback = MagicMock()
        notion_cfg = {"enabled": True, "briefings_db_id": "db-123"}
        config = _make_config(platforms_connected=[], notion=notion_cfg)
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)

        thursday = datetime(2026, 4, 16, 18, 0, tzinfo=timezone.utc)
        assert thursday.weekday() == 3  # Thursday

        with patch("cli.background.datetime") as mock_dt:
            mock_dt.now.return_value = thursday
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await bg._maybe_publish_digest()

        api.publish_digest_to_notion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_digest_not_published_twice_same_week(self) -> None:
        api = _make_api()
        api.publish_digest_to_notion = AsyncMock()
        callback = MagicMock()
        friday_18 = datetime(2026, 4, 17, 18, 0, tzinfo=timezone.utc)
        # Dedup key is Monday date of the week
        from datetime import timedelta
        monday = (friday_18 - timedelta(days=friday_18.weekday())).strftime("%Y-%m-%d")
        notion_cfg = {
            "enabled": True, "briefings_db_id": "db-123",
            "last_digest_week": monday,
        }
        config = _make_config(platforms_connected=[], notion=notion_cfg)
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)

        with patch("cli.background.datetime") as mock_dt:
            mock_dt.now.return_value = friday_18
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await bg._maybe_publish_digest()

        api.publish_digest_to_notion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_digest_skipped_when_notion_disabled(self) -> None:
        api = _make_api()
        api.publish_digest_to_notion = AsyncMock()
        callback = MagicMock()
        config = _make_config(platforms_connected=[], notion=None)
        bg = BackgroundSync(api=api, config=config, on_sync_result=callback)
        await bg._maybe_publish_digest()
        api.publish_digest_to_notion.assert_not_awaited()
