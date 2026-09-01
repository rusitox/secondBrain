"""Automatic token refresh for OAuth2 integrations.

Currently handles Microsoft Graph tokens (Outlook + Teams) via MSAL silent
refresh. Slack and Fathom tokens are long-lived and do not need refreshing.

Usage:
    token = await ensure_fresh_token(integration, db)
"""
import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration, Platform
from app.utils.encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

# Platforms that use short-lived Microsoft Graph tokens
_MS_PLATFORMS = {Platform.OUTLOOK, Platform.TEAMS}

# Refresh if token expires within this many seconds
_EXPIRY_BUFFER_SECONDS = 300  # 5 minutes


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Extract `exp` claim from a JWT without verifying the signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Add padding if needed
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return int(decoded.get("exp", 0))
    except Exception:
        return None


def is_token_expiring_soon(token: str) -> bool:
    """Return True if the token is expired or will expire within the buffer window."""
    exp = _decode_jwt_exp(token)
    if exp is None:
        # Can't determine expiry — assume it's fine (e.g. Slack opaque tokens)
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    return now >= (exp - _EXPIRY_BUFFER_SECONDS)


def _msal_refresh_sync(client_id: str, authority: str, scopes: str, cache_path: str) -> Optional[str]:
    """Synchronous MSAL silent token refresh. Run via executor to avoid blocking."""
    try:
        from msal import PublicClientApplication, SerializableTokenCache
    except ImportError:
        logger.warning("msal package not installed — cannot refresh Microsoft tokens")
        return None

    scope_list = scopes.split()
    cache_file = Path(cache_path) if cache_path else Path.home() / ".secondbrain" / "msal_cache.json"

    if not cache_file.exists():
        logger.warning("MSAL cache not found at %s — cannot refresh token silently", cache_file)
        return None

    cache = SerializableTokenCache()
    cache.deserialize(cache_file.read_text())

    app = PublicClientApplication(client_id, authority=authority, token_cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        logger.warning("No MSAL accounts found in cache — cannot refresh token silently")
        return None

    result = app.acquire_token_silent(scope_list, account=accounts[0])
    if not result or "access_token" not in result:
        logger.warning("MSAL silent refresh failed: %s", result.get("error_description") if result else "no result")
        return None

    if cache.has_state_changed:
        cache_file.write_text(cache.serialize())
        logger.debug("MSAL cache updated")

    return result["access_token"]


async def ensure_fresh_token(integration: Integration, db: AsyncSession) -> str:
    """Return a valid access token, refreshing via MSAL if it's expiring soon.

    For non-Microsoft platforms (Slack, Fathom, Notion) the token is returned
    as-is — those are long-lived and don't require periodic refresh.
    """
    current_token = decrypt_token(integration.access_token)

    if integration.platform not in _MS_PLATFORMS:
        return current_token

    if not is_token_expiring_soon(current_token):
        return current_token

    logger.info(
        "Token expiring soon for platform=%s — attempting MSAL silent refresh",
        integration.platform.value,
    )

    from app.core.config import get_settings
    settings = get_settings()

    if not settings.ms_client_id or not settings.ms_authority:
        logger.warning(
            "MS_CLIENT_ID / MS_AUTHORITY not configured — using existing token as-is"
        )
        return current_token

    loop = asyncio.get_event_loop()
    new_token = await loop.run_in_executor(
        None,
        _msal_refresh_sync,
        settings.ms_client_id,
        settings.ms_authority,
        settings.ms_scopes,
        settings.msal_cache_path,
    )

    if not new_token:
        logger.warning(
            "MSAL refresh returned no token for platform=%s — using existing token",
            integration.platform.value,
        )
        return current_token

    # Persist the fresh token to DB so all integrations on the same MS account stay fresh
    integration.access_token = encrypt_token(new_token)
    await db.flush()

    logger.info("Token refreshed via MSAL for platform=%s", integration.platform.value)
    return new_token
