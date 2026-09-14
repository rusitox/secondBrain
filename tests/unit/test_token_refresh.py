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
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.token_refresh import (
    _decode_jwt_exp,
    _ensure_fresh_fathom_token,
    _fathom_refresh_token_grant,
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


class TestFathomRefreshTokenGrant:
    @pytest.mark.asyncio
    async def test_success_returns_parsed_response(self) -> None:
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"access_token": "new-tok", "expires_in": 3600}

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)):
            result = await _fathom_refresh_token_grant("old-refresh", "client-123")

        assert result == {"access_token": "new-tok", "expires_in": 3600}

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self) -> None:
        mock_resp = MagicMock(status_code=400, text="invalid_grant")

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)):
            result = await _fathom_refresh_token_grant("old-refresh", "client-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self) -> None:
        with patch(
            "httpx.AsyncClient.post",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            result = await _fathom_refresh_token_grant("old-refresh", "client-123")

        assert result is None


class TestEnsureFreshTokenFathom:
    def _fathom_integration(self, **overrides: object) -> MagicMock:
        from app.utils.encryption import encrypt_token

        integration = MagicMock()
        integration.platform = __import__("app.models.integration", fromlist=["Platform"]).Platform.FATHOM
        integration.access_token = encrypt_token("current-access-token")
        integration.refresh_token = encrypt_token("current-refresh-token")
        integration.oauth_client_id = "client-123"
        integration.token_expires_at = None
        for key, value in overrides.items():
            setattr(integration, key, value)
        return integration

    @pytest.mark.asyncio
    async def test_never_set_up_returns_existing_token_no_refresh(self) -> None:
        integration = self._fathom_integration(oauth_client_id=None)

        with patch("app.services.token_refresh._fathom_refresh_token_grant") as mock_refresh:
            token = await ensure_fresh_token(integration, MagicMock())

        mock_refresh.assert_not_called()
        assert token == "current-access-token"

    @pytest.mark.asyncio
    async def test_not_expiring_soon_skips_refresh(self) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        integration = self._fathom_integration(token_expires_at=expires_at)

        with patch("app.services.token_refresh._fathom_refresh_token_grant") as mock_refresh:
            token = await ensure_fresh_token(integration, MagicMock())

        mock_refresh.assert_not_called()
        assert token == "current-access-token"

    @pytest.mark.asyncio
    async def test_no_tracked_expiry_refreshes_anyway(self) -> None:
        """token_expires_at=None (legacy row, or never set) — refresh rather
        than assume the token is still good."""
        integration = self._fathom_integration(token_expires_at=None)
        db = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.token_refresh._fathom_refresh_token_grant",
            AsyncMock(return_value={"access_token": "fresh-tok", "expires_in": 3600}),
        ) as mock_refresh:
            token = await ensure_fresh_token(integration, db)

        mock_refresh.assert_called_once_with("current-refresh-token", "client-123")
        assert token == "fresh-tok"

    @pytest.mark.asyncio
    async def test_expiring_soon_refreshes_and_persists(self) -> None:
        from app.utils.encryption import decrypt_token

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        integration = self._fathom_integration(token_expires_at=expires_at)
        db = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.token_refresh._fathom_refresh_token_grant",
            AsyncMock(return_value={
                "access_token": "fresh-tok", "refresh_token": "fresh-refresh", "expires_in": 3600,
            }),
        ):
            token = await _ensure_fresh_fathom_token(integration, db)

        assert token == "fresh-tok"
        assert decrypt_token(integration.access_token) == "fresh-tok"
        assert decrypt_token(integration.refresh_token) == "fresh-refresh"
        assert integration.token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=59)
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_failure_returns_existing_token(self) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        integration = self._fathom_integration(token_expires_at=expires_at)
        db = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.token_refresh._fathom_refresh_token_grant", AsyncMock(return_value=None),
        ):
            token = await _ensure_fresh_fathom_token(integration, db)

        assert token == "current-access-token"
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_response_missing_access_token_returns_existing(self) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        integration = self._fathom_integration(token_expires_at=expires_at)

        with patch(
            "app.services.token_refresh._fathom_refresh_token_grant",
            AsyncMock(return_value={"error": "invalid_grant"}),
        ):
            token = await _ensure_fresh_fathom_token(integration, MagicMock())

        assert token == "current-access-token"

    @pytest.mark.asyncio
    async def test_naive_expires_at_treated_as_utc(self) -> None:
        """A token_expires_at without tzinfo (e.g. from a raw sqlite test
        row) must not crash comparing against an aware datetime."""
        naive_future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        integration = self._fathom_integration(token_expires_at=naive_future)

        with patch("app.services.token_refresh._fathom_refresh_token_grant") as mock_refresh:
            token = await ensure_fresh_token(integration, MagicMock())

        mock_refresh.assert_not_called()
        assert token == "current-access-token"
