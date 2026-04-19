import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "
_KEY_PREFIX = "sb_"


async def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Extract and validate the current user ID from request headers.

    Authentication flow:
    1. If Authorization: Bearer sb_... header is present, verify the API key
       against bcrypt hashes in the database.
    2. If X-User-Id header is present AND app_env is not production,
       use the UUID directly (development/testing fallback).
    3. Otherwise, return 401.
    """
    try:
        settings = get_settings()
        is_production = settings.is_production
    except (ValueError, ValidationError):
        # Settings unavailable (e.g. tests without .env file).
        # Default to non-production so X-User-Id fallback works.
        is_production = False

    # Path 1: Bearer token authentication
    if authorization and authorization.startswith(_BEARER_PREFIX):
        token = authorization[len(_BEARER_PREFIX):]
        if token.startswith(_KEY_PREFIX):
            return await _verify_api_key(token, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format — must start with 'sb_'",
        )

    # Path 2: X-User-Id fallback (development/testing only)
    if x_user_id:
        if is_production:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-Id header is not accepted in production. Use Authorization: Bearer <api-key>.",
            )
        try:
            return uuid.UUID(x_user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid X-User-Id header — must be a valid UUID",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication. Provide Authorization: Bearer <api-key> header.",
    )


async def _verify_api_key(token: str, db: AsyncSession) -> uuid.UUID:
    """Look up and verify an API key against the database.

    Uses key_prefix to narrow candidates to (usually) one row,
    then bcrypt-verifies the full key.
    """
    # Import here to avoid circular imports at module load time
    from app.models.api_key import APIKey

    prefix = token[:12]
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_prefix == prefix,
            APIKey.is_active == True,  # noqa: E712
        )
    )
    candidates = result.scalars().all()

    for api_key in candidates:
        if bcrypt.checkpw(token.encode("utf-8"), api_key.key_hash.encode("utf-8")):
            # Update last_used_at
            api_key.last_used_at = datetime.now(timezone.utc)
            return api_key.user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or revoked API key",
    )
