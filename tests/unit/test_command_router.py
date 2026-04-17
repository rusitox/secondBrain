"""Unit tests for CLI command router."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cli.api_client import APIClient, APIError
from cli.commands import CommandRouter
from cli.config import CLIConfig


def _make_config(**overrides) -> CLIConfig:
    defaults = dict(
        server_url="http://test:8000",
        user_id="user-123",
        user_name="Test",
        user_email="test@test.com",
        onboarding_completed=True,
        onboarding_step=5,
        platforms_connected=["slack", "outlook"],
        identity_configured=True,
        initial_import_done=True,
        preferences={"briefing_hour": 7, "briefing_minute": 0, "alert_mode": "briefing_only"},
    )
    defaults.update(overrides)
    config = CLIConfig(**defaults)
    config.save = MagicMock()
    return config


def _make_api() -> APIClient:
    api = MagicMock(spec=APIClient)
    api.get_briefing = AsyncMock(return_value={
        "briefing": {
            "agenda": "Meeting at 10am",
            "pending_commitments": "Send report by Friday",
            "contextual_alerts": "Bob mentioned the deadline",
        }
    })
    api.list_commitments = AsyncMock(return_value=[
        {"description": "Send report", "priority": "P1", "due_date": "2026-04-18", "status": "pending"},
        {"description": "Review PR", "priority": "P2", "due_date": "2026-04-20", "status": "pending"},
    ])
    api.sync_platform = AsyncMock(return_value={
        "documents_created": 5, "documents_updated": 2, "commitments_detected": 1,
    })
    api.get_user_stats = AsyncMock(return_value={
        "documents_total": 100, "commitments_pending": 5, "commitments_overdue": 1,
        "integrations_active": 2, "integrations_total": 2, "last_sync": "2026-04-16T10:00:00",
    })
    api.get_identity = AsyncMock(return_value={
        "persona_description": "CTO at startup",
        "tone_guidelines": "Direct",
        "heuristics": {"rule_1": "Investors first"},
    })
    api.list_integrations = AsyncMock(return_value=[{"id": "int-1", "platform": "slack"}])
    api.delete_integration = AsyncMock()
    api.schedule_briefing = AsyncMock()
    return api


class TestCommandRouterBasics:
    def test_get_command_names(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        names = router.get_command_names()
        assert "/help" in names
        assert "/quit" in names
        assert "/briefing" in names

    def test_should_quit_initially_false(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        assert router.should_quit is False

    @pytest.mark.asyncio
    async def test_unknown_command(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        await router.dispatch("/nonexistent")
        # Should not raise, just print warning

    @pytest.mark.asyncio
    async def test_empty_input(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        await router.dispatch("")
        # Should not raise


class TestQuitCommand:
    @pytest.mark.asyncio
    async def test_quit(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        await router.dispatch("/quit")
        assert router.should_quit is True

    @pytest.mark.asyncio
    async def test_exit_alias(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        await router.dispatch("/exit")
        assert router.should_quit is True

    @pytest.mark.asyncio
    async def test_q_alias(self) -> None:
        router = CommandRouter(api=_make_api(), config=_make_config())
        await router.dispatch("/q")
        assert router.should_quit is True


class TestBriefingCommand:
    @pytest.mark.asyncio
    async def test_briefing_shows_content(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/briefing")
        api.get_briefing.assert_awaited_once_with("user-123")

    @pytest.mark.asyncio
    async def test_briefing_no_user(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config(user_id=None))
        await router.dispatch("/briefing")
        api.get_briefing.assert_not_awaited()


class TestCommitmentsCommand:
    @pytest.mark.asyncio
    async def test_list_pending(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/commitments")
        api.list_commitments.assert_awaited_once_with("pending")

    @pytest.mark.asyncio
    async def test_list_overdue(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/overdue")
        api.list_commitments.assert_awaited_once_with("overdue")

    @pytest.mark.asyncio
    async def test_empty_commitments(self) -> None:
        api = _make_api()
        api.list_commitments = AsyncMock(return_value=[])
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/commitments")
        # Should print "No pending commitments" without error


class TestSyncCommand:
    @pytest.mark.asyncio
    async def test_sync_all_platforms(self) -> None:
        api = _make_api()
        config = _make_config(platforms_connected=["slack", "outlook"])
        router = CommandRouter(api=api, config=config)
        await router.dispatch("/sync")
        assert api.sync_platform.await_count == 2

    @pytest.mark.asyncio
    async def test_sync_specific_platform(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/sync slack")
        api.sync_platform.assert_awaited_once_with("slack")

    @pytest.mark.asyncio
    async def test_sync_no_platforms(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config(platforms_connected=[]))
        await router.dispatch("/sync")
        api.sync_platform.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_failure_handled(self) -> None:
        api = _make_api()
        api.sync_platform = AsyncMock(side_effect=APIError(500, "Sync failed"))
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/sync slack")
        # Should not raise


class TestStatusCommand:
    @pytest.mark.asyncio
    async def test_status_shows_stats(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/status")
        api.get_user_stats.assert_awaited_once_with("user-123")


class TestDisconnectCommand:
    @pytest.mark.asyncio
    async def test_disconnect_platform(self) -> None:
        api = _make_api()
        config = _make_config(platforms_connected=["slack", "outlook"])
        router = CommandRouter(api=api, config=config)
        await router.dispatch("/disconnect slack")
        api.delete_integration.assert_awaited_once()
        assert "slack" not in config.platforms_connected
        config.save.assert_called()

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config(platforms_connected=["outlook"]))
        await router.dispatch("/disconnect slack")
        api.delete_integration.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_no_args(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        await router.dispatch("/disconnect")
        api.delete_integration.assert_not_awaited()


class TestIdentityCommand:
    @pytest.mark.asyncio
    async def test_view_identity(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        with patch("cli.commands.console") as mock_console:
            mock_console.input = MagicMock(return_value="n")
            await router.dispatch("/identity")
        api.get_identity.assert_awaited_once_with("user-123")


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_lists_commands(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        # Should not raise
        await router.dispatch("/help")


class TestSettingsCommand:
    @pytest.mark.asyncio
    async def test_settings_shows_prefs(self) -> None:
        api = _make_api()
        router = CommandRouter(api=api, config=_make_config())
        # Should not raise
        await router.dispatch("/settings")


class TestApiErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_caught(self) -> None:
        api = _make_api()
        api.get_briefing = AsyncMock(side_effect=APIError(500, "Server error"))
        router = CommandRouter(api=api, config=_make_config())
        # Should not raise
        await router.dispatch("/briefing")
