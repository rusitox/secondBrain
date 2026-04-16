import uuid
import logging
from typing import Optional

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


async def get_current_user_id(
    x_user_id: Optional[str] = Header(None),
) -> uuid.UUID:
    """Extract and validate the current user ID from request headers.

    Development placeholder: reads from X-User-Id header.
    In production, this will be replaced with proper OAuth2/JWT auth.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header",
        )
    try:
        return uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-User-Id header — must be a valid UUID",
        )
