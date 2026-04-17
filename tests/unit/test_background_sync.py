"""Unit tests for background sync."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from cli.api_client import APIClient, APIError
from cli.background import BackgroundSync
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
