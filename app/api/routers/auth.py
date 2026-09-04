import hmac
import logging
import secrets
import uuid
from typing import List

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.schemas.auth import APIKeyCreate, APIKeyCreated, APIKeyList, APIKeyResponse, LoginRequest, LoginResponse
from app.core.config import get_settings
from app.models.api_key import APIKey
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_KEY_LABEL = "sb_live_"


def _generate_api_key() -> str:
    """Generate a new API key: sb_live_<32 hex chars>."""
    return _KEY_LABEL + secrets.token_hex(16)


def _hash_key(plaintext: str) -> str:
    """Hash an API key with bcrypt."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_key(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext key against its bcrypt hash."""
    return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Exchange email + portal password for an API key.

    The portal_password is set via the PORTAL_PASSWORD env var.
    If not configured, the endpoint returns 503 (use API keys directly).
    """
    settings = get_settings()

    if not settings.portal_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portal login is not configured. Set PORTAL_PASSWORD in .env.",
        )

    if not hmac.compare_digest(body.password, settings.portal_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    # Find user by email
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    # Always create a fresh session key for the portal
    plaintext = _generate_api_key()
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:12]

    api_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name="portal-login",
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("Portal login: user=%s prefix=%s", user.email, key_prefix)

    return {"api_key": plaintext, "user_name": user.full_name}


@router.post("/api-keys", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreate,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new API key. The full key is returned only once."""
    plaintext = _generate_api_key()
    key_hash = _hash_key(plaintext)
    # Store the first 12 chars (sb_live_ + first 4 hex) for fast DB lookup
    key_prefix = plaintext[:12]

    api_key = APIKey(
        user_id=current_user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("API key created: prefix=%s name=%s user=%s", key_prefix, body.name, current_user_id)

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_prefix": key_prefix,
        "created_at": api_key.created_at,
        "last_used_at": None,
        "is_active": True,
        "key": plaintext,
    }


@router.get("/api-keys", response_model=APIKeyList)
async def list_api_keys(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all API keys for the current user (no secrets returned)."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user_id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return {"keys": keys}


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key (soft delete — sets is_active=False)."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.id == key_id, APIKey.user_id == current_user_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    logger.info("API key revoked: prefix=%s user=%s", api_key.key_prefix, current_user_id)


@router.post("/api-keys/{key_id}/regenerate", response_model=APIKeyCreated)
async def regenerate_api_key(
    key_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the old key and create a new one. Returns the new plaintext key once."""
    # Find and revoke the old key
    result = await db.execute(
        select(APIKey)
        .where(APIKey.id == key_id, APIKey.user_id == current_user_id)
    )
    old_key = result.scalar_one_or_none()
    if not old_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    old_key.is_active = False

    # Generate new key with the same name
    plaintext = _generate_api_key()
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:12]

    new_key = APIKey(
        user_id=current_user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=old_key.name,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    logger.info(
        "API key regenerated: old_prefix=%s new_prefix=%s user=%s",
        old_key.key_prefix, key_prefix, current_user_id,
    )

    return {
        "id": new_key.id,
        "name": new_key.name,
        "key_prefix": key_prefix,
        "created_at": new_key.created_at,
        "last_used_at": None,
        "is_active": True,
        "key": plaintext,
    }


@router.post("/bootstrap", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def bootstrap_api_key(
    body: APIKeyCreate,
    x_user_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an API key using X-User-Id header. Development mode only.

    This endpoint exists to solve the bootstrapping problem: how to create
    the first API key when all other endpoints require Bearer auth.
    """
    settings = get_settings()
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bootstrap endpoint is disabled in production. "
            "Use: python -m app.cli.create_api_key --user-id <UUID>",
        )

    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-Id — must be a valid UUID",
        )

    plaintext = _generate_api_key()
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:12]

    api_key = APIKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.warning(
        "API key created via bootstrap endpoint: prefix=%s user=%s",
        key_prefix, user_id,
    )

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_prefix": key_prefix,
        "created_at": api_key.created_at,
        "last_used_at": None,
        "is_active": True,
        "key": plaintext,
    }
