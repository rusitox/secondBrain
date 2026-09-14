"""One-time interactive OAuth setup for Fathom's MCP server.

Fathom's MCP server (https://api.fathom.ai/mcp) requires OAuth 2.1
(authorization_code + PKCE via dynamic client registration), not a static
API key — see app/services/connectors/fathom.py's module docstring. This
script drives the one-time interactive consent (opens a browser, runs a
local callback server to catch the redirect) and persists the resulting
access/refresh tokens on the Fathom Integration row.

Ongoing refresh happens automatically afterwards via
app/services/token_refresh.py's refresh_token grant — this script only
needs to run once, or again if the refresh_token itself is ever revoked.

Prerequisite: a Fathom Integration row must already exist (any placeholder
access_token — this script overwrites it). Create one via `/connect fathom`
in the CLI first if none exists.

Usage:
    python scripts/connect_fathom_oauth.py
"""
import asyncio
import base64
import hashlib
import http.server
import logging
import os
import pathlib
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

os.environ["DEBUG"] = "false"
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

import httpx
import webbrowser
from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.integration import Integration, Platform
from app.utils.encryption import encrypt_token

USER_ID = uuid.UUID("889ff4f4-b782-4e9f-bfb1-e310ae132827")

AUTHORIZATION_ENDPOINT = "https://fathom.video/mcp/oauth/authorize"
TOKEN_ENDPOINT = "https://api.fathom.ai/mcp/oauth/token"
REGISTRATION_ENDPOINT = "https://api.fathom.ai/mcp/oauth/register"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
CALLBACK_TIMEOUT_SECONDS = 300


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the OAuth redirect's `code`/`state`/`error` query params.

    Class-level `result` because HTTPServer instantiates a fresh handler
    per request — there's no per-instance state to hand back to main().
    """

    result: Dict[str, Optional[str]] = {}

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        if "code" in params or "error" in params:
            _CallbackHandler.result["code"] = params.get("code", [None])[0]
            _CallbackHandler.result["state"] = params.get("state", [None])[0]
            _CallbackHandler.result["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<html><body>Listo, podés cerrar esta pestaña y volver a la terminal.</body></html>".encode()
        )

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging — noisy for a one-shot script


def _pkce_pair() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def _register_client() -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(REGISTRATION_ENDPOINT, json={
            "client_name": "secondBrain",
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        })
        resp.raise_for_status()
        return str(resp.json()["client_id"])


async def _exchange_code(code: str, verifier: str, client_id: str) -> Dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TOKEN_ENDPOINT, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        })
        resp.raise_for_status()
        return dict(resp.json())


def _wait_for_callback() -> Dict[str, Optional[str]]:
    """Block (in the main thread — this is an interactive one-shot script)
    until the browser hits REDIRECT_URI, or CALLBACK_TIMEOUT_SECONDS elapse.

    Loops handle_request() rather than a single call so a stray extra
    request (e.g. the browser tab's favicon.ico) doesn't consume the one
    request we're actually waiting for.
    """
    _CallbackHandler.result = {}
    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    server.timeout = 5.0
    deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            server.handle_request()
            if _CallbackHandler.result.get("code") or _CallbackHandler.result.get("error"):
                break
    finally:
        server.server_close()
    return _CallbackHandler.result


async def main() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(
            select(Integration).where(
                Integration.user_id == USER_ID, Integration.platform == Platform.FATHOM,
            )
        )
        integration = result.scalar_one_or_none()
        if integration is None:
            print(
                "No Fathom integration found — run `/connect fathom` in the CLI first "
                "(any placeholder token works, this script replaces it)."
            )
            return

        if integration.oauth_client_id:
            client_id = integration.oauth_client_id
            print("Reusing already-registered OAuth client.")
        else:
            print("Registering a new OAuth client with Fathom...")
            client_id = await _register_client()

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        auth_url = f"{AUTHORIZATION_ENDPOINT}?" + urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mcp",
        })

        print(f"Abriendo el navegador para autorizar el acceso a Fathom...\n{auth_url}\n")
        webbrowser.open(auth_url)
        print(f"Esperando la autorización (hasta {CALLBACK_TIMEOUT_SECONDS}s)...")

        callback = _wait_for_callback()
        if not callback.get("code"):
            print(f"No se recibió el código de autorización (timeout o error: {callback.get('error')}).")
            return
        if callback.get("state") != state:
            print("El parámetro 'state' no coincide con lo esperado — posible CSRF, abortando.")
            return

        print("Intercambiando el código por tokens...")
        token_data = await _exchange_code(str(callback["code"]), verifier, client_id)

        integration.access_token = encrypt_token(str(token_data["access_token"]))
        if token_data.get("refresh_token"):
            integration.refresh_token = encrypt_token(str(token_data["refresh_token"]))
        integration.oauth_client_id = client_id
        expires_in = token_data.get("expires_in")
        if isinstance(expires_in, (int, float)):
            integration.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        integration.last_sync_status = None
        integration.last_sync_error = None
        await db.commit()

        print("Listo — Fathom queda conectado vía OAuth. El sync automático ya puede usar esta integración.")


if __name__ == "__main__":
    asyncio.run(main())
