"""Unit tests for scripts/connect_fathom_oauth.py.

The full interactive flow (real browser + local HTTP server) can't be
unit-tested — these cover the pure/mockable pieces: PKCE generation, the
callback handler's query-param parsing, DCR/token-exchange HTTP calls
(httpx mocked), and main()'s branching with the DB and the interactive
wait mocked out.
"""
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = str(pathlib.Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.connect_fathom_oauth import (
    REDIRECT_URI,
    _CallbackHandler,
    _exchange_code,
    _pkce_pair,
    _register_client,
    main,
)


def _make_integration(
    oauth_client_id: Optional[str] = None,
) -> MagicMock:
    mock = MagicMock()
    mock.oauth_client_id = oauth_client_id
    return mock


def _make_db_session(integration: Optional[MagicMock]) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = integration

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


class TestPkcePair:
    def test_verifier_and_challenge_differ(self) -> None:
        verifier, challenge = _pkce_pair()
        assert verifier != challenge

    def test_verifier_within_rfc_length_bounds(self) -> None:
        """RFC 7636: code_verifier must be 43-128 characters."""
        verifier, _ = _pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_sha256_of_verifier(self) -> None:
        import base64
        import hashlib

        verifier, challenge = _pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert challenge == expected

    def test_successive_calls_are_unique(self) -> None:
        v1, _ = _pkce_pair()
        v2, _ = _pkce_pair()
        assert v1 != v2


class TestCallbackHandlerParsing:
    def _dispatch(self, path: str) -> dict:
        _CallbackHandler.result = {}
        handler = _CallbackHandler.__new__(_CallbackHandler)
        handler.path = path
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        return dict(_CallbackHandler.result)

    def test_extracts_code_and_state(self) -> None:
        result = self._dispatch("/callback?code=abc123&state=xyz789")
        assert result == {"code": "abc123", "state": "xyz789", "error": None}

    def test_extracts_error(self) -> None:
        result = self._dispatch("/callback?error=access_denied&state=xyz789")
        assert result["error"] == "access_denied"
        assert result["code"] is None

    def test_ignores_unrelated_requests(self) -> None:
        """A stray request (e.g. favicon.ico) with no code/error/state must
        not overwrite `result` with a dict of Nones."""
        result = self._dispatch("/favicon.ico")
        assert result == {}

    def test_responds_200_regardless(self) -> None:
        _CallbackHandler.result = {}
        handler = _CallbackHandler.__new__(_CallbackHandler)
        handler.path = "/callback?code=abc"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()
        handler.send_response.assert_called_once_with(200)


class TestRegisterClient:
    @pytest.mark.asyncio
    async def test_posts_client_name_and_redirect_uri(self) -> None:
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"client_id": "new-client-id"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
            client_id = await _register_client()

        assert client_id == "new-client-id"
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["client_name"] == "secondBrain"
        assert kwargs["json"]["redirect_uris"] == [REDIRECT_URI]


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_posts_authorization_code_grant(self) -> None:
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"access_token": "tok", "refresh_token": "rtok", "expires_in": 86400}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
            result = await _exchange_code("auth-code", "verifier-value", "client-id")

        assert result == {"access_token": "tok", "refresh_token": "rtok", "expires_in": 86400}
        _, kwargs = mock_post.call_args
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "auth-code"
        assert kwargs["data"]["code_verifier"] == "verifier-value"


class TestMain:
    @pytest.mark.asyncio
    async def test_no_integration_prints_message_and_returns(self, capsys: pytest.CaptureFixture) -> None:
        db_session = _make_db_session(None)
        factory = MagicMock(return_value=db_session)

        with patch("scripts.connect_fathom_oauth.get_session_factory", return_value=factory):
            await main()

        assert "run `/connect fathom`" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_no_code_received_prints_timeout_message(self, capsys: pytest.CaptureFixture) -> None:
        integration = _make_integration(oauth_client_id="existing-client")
        db_session = _make_db_session(integration)
        factory = MagicMock(return_value=db_session)

        with patch("scripts.connect_fathom_oauth.get_session_factory", return_value=factory), \
             patch("scripts.connect_fathom_oauth.webbrowser.open"), \
             patch("scripts.connect_fathom_oauth._wait_for_callback", return_value={}):
            await main()

        assert "No se recibió el código" in capsys.readouterr().out
        db_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_mismatch_aborts(self, capsys: pytest.CaptureFixture) -> None:
        integration = _make_integration(oauth_client_id="existing-client")
        db_session = _make_db_session(integration)
        factory = MagicMock(return_value=db_session)

        with patch("scripts.connect_fathom_oauth.get_session_factory", return_value=factory), \
             patch("scripts.connect_fathom_oauth.webbrowser.open"), \
             patch(
                 "scripts.connect_fathom_oauth._wait_for_callback",
                 return_value={"code": "abc", "state": "wrong-state", "error": None},
             ):
            await main()

        assert "posible CSRF" in capsys.readouterr().out
        db_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_persists_tokens(self, capsys: pytest.CaptureFixture) -> None:
        integration = _make_integration(oauth_client_id="existing-client")
        db_session = _make_db_session(integration)
        factory = MagicMock(return_value=db_session)

        captured_state = {}

        def fake_wait_for_callback() -> dict:
            # main() generates state internally; capture it via the module's
            # own secrets.token_urlsafe call being deterministic isn't
            # possible, so instead patch secrets.token_urlsafe to a fixed
            # value and match it here.
            return {"code": "auth-code-123", "state": "fixed-state", "error": None}

        with patch("scripts.connect_fathom_oauth.get_session_factory", return_value=factory), \
             patch("scripts.connect_fathom_oauth.webbrowser.open"), \
             patch("scripts.connect_fathom_oauth.secrets.token_urlsafe", return_value="fixed-state"), \
             patch("scripts.connect_fathom_oauth._wait_for_callback", side_effect=fake_wait_for_callback), \
             patch(
                 "scripts.connect_fathom_oauth._exchange_code",
                 AsyncMock(return_value={
                     "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 86400,
                 }),
             ):
            await main()

        from app.utils.encryption import decrypt_token

        assert decrypt_token(integration.access_token) == "new-access"
        assert decrypt_token(integration.refresh_token) == "new-refresh"
        assert integration.oauth_client_id == "existing-client"
        assert integration.token_expires_at > datetime.now(timezone.utc)
        db_session.commit.assert_called_once()
        assert "Listo" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_registers_new_client_when_none_stored(self) -> None:
        integration = _make_integration(oauth_client_id=None)
        db_session = _make_db_session(integration)
        factory = MagicMock(return_value=db_session)

        with patch("scripts.connect_fathom_oauth.get_session_factory", return_value=factory), \
             patch("scripts.connect_fathom_oauth.webbrowser.open"), \
             patch("scripts.connect_fathom_oauth._register_client", AsyncMock(return_value="freshly-registered")) as mock_register, \
             patch("scripts.connect_fathom_oauth.secrets.token_urlsafe", return_value="fixed-state"), \
             patch(
                 "scripts.connect_fathom_oauth._wait_for_callback",
                 return_value={"code": "auth-code", "state": "fixed-state", "error": None},
             ), \
             patch(
                 "scripts.connect_fathom_oauth._exchange_code",
                 AsyncMock(return_value={"access_token": "tok", "expires_in": 3600}),
             ):
            await main()

        mock_register.assert_called_once()
        assert integration.oauth_client_id == "freshly-registered"
