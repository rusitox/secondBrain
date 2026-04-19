"""Unit tests for Phase 5 — CLI auth, APIClient Bearer headers, remote mode."""
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.api_client import APIClient
from cli.config import CLIConfig


class TestAPIClientHeaders:
    """Test that APIClient sends the correct auth header based on mode."""

    def test_headers_with_api_key(self) -> None:
        client = APIClient(server_url="http://example.com", api_key="sb_live_abc123")
        headers = client._headers()
        assert headers["Authorization"] == "Bearer sb_live_abc123"
        assert "X-User-Id" not in headers

    def test_headers_with_user_id(self) -> None:
        client = APIClient(
            server_url="http://localhost:8000",
            user_id="some-uuid",
        )
        headers = client._headers()
        assert headers["X-User-Id"] == "some-uuid"
        assert "Authorization" not in headers

    def test_headers_api_key_takes_precedence(self) -> None:
        client = APIClient(
            server_url="http://example.com",
            user_id="some-uuid",
            api_key="sb_live_xyz",
        )
        headers = client._headers()
        assert headers["Authorization"] == "Bearer sb_live_xyz"
        assert "X-User-Id" not in headers

    def test_headers_no_auth(self) -> None:
        client = APIClient(server_url="http://localhost:8000")
        headers = client._headers()
        assert len(headers) == 0


class TestLoginFlow:
    """Test the login flow logic."""

    @pytest.mark.asyncio
    async def test_login_already_logged_in(self) -> None:
        from cli.auth import login

        config = CLIConfig(api_key="sb_live_existing", user_name="Test")
        result = await login(config)
        assert result is False

    @pytest.mark.asyncio
    async def test_login_empty_key(self) -> None:
        from cli.auth import login

        config = CLIConfig()
        with patch("cli.auth._ask", side_effect=["http://example.com:8080", ""]):
            result = await login(config)
        assert result is False
        assert config.api_key is None

    @pytest.mark.asyncio
    async def test_login_invalid_key_format(self) -> None:
        from cli.auth import login

        config = CLIConfig()
        with patch("cli.auth._ask", side_effect=["http://example.com:8080", "invalid_key"]):
            result = await login(config)
        assert result is False

    @pytest.mark.asyncio
    async def test_login_success(self) -> None:
        from cli.auth import login

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = CLIConfig(_config_path=path)

            mock_api_cls = MagicMock()
            mock_api = AsyncMock()
            mock_api.health_check.return_value = True
            mock_api.get_me.return_value = {
                "id": "uuid-123",
                "full_name": "Mariano",
                "email": "m@example.com",
            }
            mock_api.close = AsyncMock()
            mock_api_cls.return_value = mock_api

            with patch("cli.auth._ask", side_effect=["http://oracle-vm:8080", "sb_live_test123"]), \
                 patch("cli.auth.APIClient", mock_api_cls):
                result = await login(config)

            assert result is True
            assert config.api_key == "sb_live_test123"
            assert config.server_url == "http://oracle-vm:8080"
            assert config.user_id == "uuid-123"
            assert config.user_name == "Mariano"
            assert config.user_email == "m@example.com"

    @pytest.mark.asyncio
    async def test_login_server_unreachable(self) -> None:
        from cli.auth import login

        config = CLIConfig()
        mock_api_cls = MagicMock()
        mock_api = AsyncMock()
        mock_api.health_check.return_value = False
        mock_api.close = AsyncMock()
        mock_api_cls.return_value = mock_api

        with patch("cli.auth._ask", side_effect=["http://example.com:8080", "sb_live_test123"]), \
             patch("cli.auth.APIClient", mock_api_cls):
            result = await login(config)

        assert result is False
        assert config.api_key is None

    @pytest.mark.asyncio
    async def test_login_auth_rejected(self) -> None:
        from cli.auth import login
        from cli.api_client import APIError

        config = CLIConfig()
        mock_api_cls = MagicMock()
        mock_api = AsyncMock()
        mock_api.health_check.return_value = True
        mock_api.get_me.side_effect = APIError(401, "Invalid API key")
        mock_api.close = AsyncMock()
        mock_api_cls.return_value = mock_api

        with patch("cli.auth._ask", side_effect=["http://example.com:8080", "sb_live_bad"]), \
             patch("cli.auth.APIClient", mock_api_cls):
            result = await login(config)

        assert result is False
        assert config.api_key is None

    @pytest.mark.asyncio
    async def test_login_default_url(self) -> None:
        """Empty URL input uses default remote URL."""
        from cli.auth import login

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = CLIConfig(_config_path=path)

            mock_api_cls = MagicMock()
            mock_api = AsyncMock()
            mock_api.health_check.return_value = True
            mock_api.get_me.return_value = {
                "id": "uuid-1", "full_name": "User", "email": "u@e.com",
            }
            mock_api.close = AsyncMock()
            mock_api_cls.return_value = mock_api

            # Empty string for URL -> uses default
            with patch("cli.auth._ask", side_effect=["", "sb_live_key"]), \
                 patch("cli.auth.APIClient", mock_api_cls):
                result = await login(config)

            assert result is True
            # Should use the default remote URL
            call_args = mock_api_cls.call_args
            assert "oracle-vm" in call_args[1].get("server_url", call_args[0][0] if call_args[0] else "")


class TestLogoutFlow:
    """Test the logout flow."""

    @pytest.mark.asyncio
    async def test_logout_clears_credentials(self) -> None:
        from cli.auth import logout

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = CLIConfig(
                _config_path=path,
                api_key="sb_live_test",
                user_id="uuid-1",
                user_name="Test",
                user_email="t@e.com",
                server_url="http://oracle-vm:8080",
            )

            await logout(config)

            assert config.api_key is None
            assert config.user_id is None
            assert config.user_name is None
            assert config.user_email is None
            # Server URL should be preserved
            assert config.server_url == "http://oracle-vm:8080"

    @pytest.mark.asyncio
    async def test_logout_not_logged_in(self) -> None:
        from cli.auth import logout

        config = CLIConfig()
        # Should not raise
        await logout(config)
        assert config.api_key is None


class TestServerManagerRemoteGuard:
    """Test that ServerManager raises in remote mode."""

    def test_remote_mode_raises(self) -> None:
        from cli.server import ServerManager

        config = CLIConfig(server_url="http://oracle-vm:8080")
        with pytest.raises(RuntimeError, match="remote mode"):
            ServerManager(config)

    def test_local_mode_ok(self) -> None:
        from cli.server import ServerManager

        config = CLIConfig(server_url="http://localhost:8000")
        # Should not raise
        server = ServerManager(config)
        assert server is not None


class TestConfigPermissionWarning:
    """Test config file permission security warning."""

    def test_warns_on_open_permissions(self) -> None:
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"server_url": "http://localhost:8000"}')
            # Make world-readable
            path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

            import logging
            with patch("cli.config.logger") as mock_logger:
                CLIConfig.load(path)
                mock_logger.warning.assert_called_once()
                assert "readable" in mock_logger.warning.call_args[0][0]

    def test_no_warning_on_restricted_permissions(self) -> None:
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"server_url": "http://localhost:8000"}')
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            with patch("cli.config.logger") as mock_logger:
                CLIConfig.load(path)
                mock_logger.warning.assert_not_called()


class TestGetMeEndpoint:
    """Test GET /users/me API client method."""

    @pytest.mark.asyncio
    async def test_get_me_calls_correct_path(self) -> None:
        client = APIClient(server_url="http://localhost:8000", api_key="sb_live_test")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "uuid-1", "full_name": "Test"}
            result = await client.get_me()
            mock_req.assert_called_once_with("GET", "/users/me")
            assert result["id"] == "uuid-1"
