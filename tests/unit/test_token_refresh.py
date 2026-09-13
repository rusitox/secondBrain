"""Unit tests for app.services.token_refresh — MSAL silent token refresh
for Outlook/Teams.

Covers the corrupted-cache regression: Outlook and Teams share one MSAL
cache file, and their sync jobs (independently scheduled) landed in the
same tick, each trying to read-modify-write it with no locking — the
resulting torn write left "Extra data" trailing the valid JSON, taking
both integrations down with the same cryptic error at the same
last_sync_at. _msal_refresh_sync now serializes access with a
threading.Lock and handles a corrupted cache file as a clean, logged
failure instead of an unhandled JSONDecodeError.
"""
import base64
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.token_refresh import (
    _decode_jwt_exp,
    _msal_refresh_sync,
    ensure_fresh_token,
    is_token_expiring_soon,
)


def _make_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


class TestDecodeJwtExp:
    def test_extracts_exp_claim(self) -> None:
        token = _make_jwt(1234567890)
        assert _decode_jwt_exp(token) == 1234567890

    def test_returns_none_for_malformed_token(self) -> None:
        assert _decode_jwt_exp("not-a-jwt") is None

    def test_returns_none_for_non_jwt_opaque_token(self) -> None:
        assert _decode_jwt_exp("xoxb-opaque-slack-token") is None


class TestIsTokenExpiringSoon:
    def test_true_when_within_buffer(self) -> None:
        exp = int((datetime.now(timezone.utc) + timedelta(seconds=60)).timestamp())
        assert is_token_expiring_soon(_make_jwt(exp)) is True

    def test_false_when_far_from_expiry(self) -> None:
        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        assert is_token_expiring_soon(_make_jwt(exp)) is False

    def test_false_when_expiry_undecodable(self) -> None:
        """Opaque tokens (Slack) have no exp claim — fail open, don't force a refresh."""
        assert is_token_expiring_soon("xoxb-opaque-slack-token") is False


class TestMsalRefreshSyncCorruptedCache:
    def test_corrupted_cache_returns_none_without_raising(self, tmp_path) -> None:
        cache_file = tmp_path / "msal_cache.json"
        cache_file.write_text("{}\n}")  # valid JSON object + trailing garbage

        result = _msal_refresh_sync(
            client_id="client", authority="https://login.microsoftonline.com/x",
            scopes="Mail.Read", cache_path=str(cache_file),
        )

        assert result is None

    def test_missing_cache_file_returns_none(self, tmp_path) -> None:
        result = _msal_refresh_sync(
            client_id="client", authority="https://login.microsoftonline.com/x",
            scopes="Mail.Read", cache_path=str(tmp_path / "does_not_exist.json"),
        )
        assert result is None

    def test_lock_does_not_deadlock_across_sequential_calls(self, tmp_path) -> None:
        """Regression guard for the fix's own locking — a `with` block that
        never releases would hang every subsequent call forever."""
        cache_file = tmp_path / "msal_cache.json"
        cache_file.write_text("not json at all")

        start = time.monotonic()
        for _ in range(3):
            result = _msal_refresh_sync(
                client_id="client", authority="https://login.microsoftonline.com/x",
                scopes="Mail.Read", cache_path=str(cache_file),
            )
            assert result is None
        assert time.monotonic() - start < 5


class TestMsalRefreshSyncHappyPath:
    def test_successful_silent_refresh_updates_cache_and_returns_token(self, tmp_path) -> None:
        cache_file = tmp_path / "msal_cache.json"
        cache_file.write_text('{"AccessToken": {}}')

        mock_account = {"username": "mariano@example.com"}
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [mock_account]
        mock_app.acquire_token_silent.return_value = {"access_token": "fresh-token"}

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"AccessToken": {"updated": true}}'

        with patch("msal.SerializableTokenCache", return_value=mock_cache), \
             patch("msal.PublicClientApplication", return_value=mock_app):
            result = _msal_refresh_sync(
                client_id="client", authority="https://login.microsoftonline.com/x",
                scopes="Mail.Read Calendars.Read", cache_path=str(cache_file),
            )

        assert result == "fresh-token"
        assert cache_file.read_text() == '{"AccessToken": {"updated": true}}'

    def test_no_accounts_returns_none(self, tmp_path) -> None:
        cache_file = tmp_path / "msal_cache.json"
        cache_file.write_text('{"AccessToken": {}}')

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []

        with patch("msal.SerializableTokenCache", return_value=MagicMock()), \
             patch("msal.PublicClientApplication", return_value=mock_app):
            result = _msal_refresh_sync(
                client_id="client", authority="https://login.microsoftonline.com/x",
                scopes="Mail.Read", cache_path=str(cache_file),
            )

        assert result is None

    def test_silent_refresh_failure_returns_none(self, tmp_path) -> None:
        cache_file = tmp_path / "msal_cache.json"
        cache_file.write_text('{"AccessToken": {}}')

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "mariano@example.com"}]
        mock_app.acquire_token_silent.return_value = {"error_description": "interaction_required"}

        with patch("msal.SerializableTokenCache", return_value=MagicMock()), \
             patch("msal.PublicClientApplication", return_value=mock_app):
            result = _msal_refresh_sync(
                client_id="client", authority="https://login.microsoftonline.com/x",
                scopes="Mail.Read", cache_path=str(cache_file),
            )

        assert result is None


class TestEnsureFreshToken:
    @pytest.mark.asyncio
    async def test_non_ms_platform_returns_token_as_is(self) -> None:
        from app.models.integration import Platform
        from app.utils.encryption import encrypt_token

        integration = MagicMock()
        integration.platform = Platform.SLACK
        integration.access_token = encrypt_token("xoxb-slack-token")

        token = await ensure_fresh_token(integration, MagicMock())
        assert token == "xoxb-slack-token"

    @pytest.mark.asyncio
    async def test_ms_platform_not_expiring_soon_skips_refresh(self) -> None:
        from app.models.integration import Platform
        from app.utils.encryption import encrypt_token

        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        integration = MagicMock()
        integration.platform = Platform.OUTLOOK
        integration.access_token = encrypt_token(_make_jwt(exp))

        with patch("app.services.token_refresh._msal_refresh_sync") as mock_refresh:
            token = await ensure_fresh_token(integration, MagicMock())

        mock_refresh.assert_not_called()
        assert token == _make_jwt(exp)

    @pytest.mark.asyncio
    async def test_ms_platform_expiring_without_client_config_returns_existing_token(self) -> None:
        from app.models.integration import Platform
        from app.utils.encryption import encrypt_token

        exp = int((datetime.now(timezone.utc) + timedelta(seconds=10)).timestamp())
        expiring_token = _make_jwt(exp)
        integration = MagicMock()
        integration.platform = Platform.OUTLOOK
        integration.access_token = encrypt_token(expiring_token)

        settings = MagicMock(ms_client_id="", ms_authority="")
        with patch("app.core.config.get_settings", return_value=settings):
            token = await ensure_fresh_token(integration, MagicMock())

        assert token == expiring_token
