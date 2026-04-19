"""Tests for API key authentication (Phase 1)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest

from app.api.routers.auth import _generate_api_key, _hash_key, _verify_key


# ---------------------------------------------------------------------------
# Key generation / format
# ---------------------------------------------------------------------------

class TestKeyGeneration:
    def test_key_format(self) -> None:
        key = _generate_api_key()
        assert key.startswith("sb_live_")
        assert len(key) == 40  # "sb_live_" (8) + 32 hex chars

    def test_key_prefix_is_unique(self) -> None:
        """First 12 chars should differ between keys (includes 4 random hex)."""
        prefixes = {_generate_api_key()[:12] for _ in range(100)}
        assert len(prefixes) == 100

    def test_key_uniqueness(self) -> None:
        keys = {_generate_api_key() for _ in range(100)}
        assert len(keys) == 100


# ---------------------------------------------------------------------------
# bcrypt hash / verify
# ---------------------------------------------------------------------------

class TestBcryptRoundtrip:
    def test_hash_and_verify(self) -> None:
        key = _generate_api_key()
        hashed = _hash_key(key)
        assert _verify_key(key, hashed) is True

    def test_wrong_key_fails(self) -> None:
        key = _generate_api_key()
        hashed = _hash_key(key)
        assert _verify_key("sb_live_wrong_key_1234567890abcdef", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        key = _generate_api_key()
        hashed = _hash_key(key)
        assert hashed != key
        assert hashed.startswith("$2")  # bcrypt prefix


# ---------------------------------------------------------------------------
# get_current_user_id — X-User-Id fallback
# ---------------------------------------------------------------------------

class TestXUserIdFallback:
    @pytest.mark.asyncio
    async def test_x_user_id_accepted_in_dev(self) -> None:
        """X-User-Id header works in non-production mode."""
        from app.core.security import get_current_user_id

        user_id = uuid.uuid4()
        mock_db = AsyncMock()

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=False)
            result = await get_current_user_id(
                authorization=None,
                x_user_id=str(user_id),
                db=mock_db,
            )
        assert result == user_id

    @pytest.mark.asyncio
    async def test_x_user_id_rejected_in_production(self) -> None:
        """X-User-Id header is rejected in production mode."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        mock_db = AsyncMock()

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=True)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization=None,
                    x_user_id=str(uuid.uuid4()),
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401
        assert "not accepted in production" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_uuid_rejected(self) -> None:
        """Invalid UUID in X-User-Id raises 401."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        mock_db = AsyncMock()

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=False)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization=None,
                    x_user_id="not-a-uuid",
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_raises_401(self) -> None:
        """No auth headers at all raises 401."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        mock_db = AsyncMock()

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=False)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization=None,
                    x_user_id=None,
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user_id — Bearer token
# ---------------------------------------------------------------------------

class TestBearerAuth:
    @pytest.mark.asyncio
    async def test_valid_bearer_token(self) -> None:
        """Valid Bearer token returns the correct user_id."""
        from app.core.security import get_current_user_id

        user_id = uuid.uuid4()
        plaintext = _generate_api_key()
        hashed = _hash_key(plaintext)

        # Mock DB to return a matching APIKey
        mock_api_key = MagicMock()
        mock_api_key.key_hash = hashed
        mock_api_key.user_id = user_id
        mock_api_key.last_used_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_api_key]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=True)
            result = await get_current_user_id(
                authorization="Bearer " + plaintext,
                x_user_id=None,
                db=mock_db,
            )
        assert result == user_id

    @pytest.mark.asyncio
    async def test_invalid_bearer_token(self) -> None:
        """Invalid Bearer token raises 401."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=True)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization="Bearer sb_live_0000000000000000000000000000dead",
                    x_user_id=None,
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_revoked_key_not_returned(self) -> None:
        """Revoked keys (is_active=False) are not returned by the query."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        # Simulate no active keys matching the prefix
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=True)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization="Bearer sb_live_revoked_key_that_does_not_exist",
                    x_user_id=None,
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_key_format_rejected(self) -> None:
        """Bearer token without sb_ prefix is rejected."""
        from fastapi import HTTPException
        from app.core.security import get_current_user_id

        mock_db = AsyncMock()

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(is_production=True)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(
                    authorization="Bearer not_a_valid_key_format",
                    x_user_id=None,
                    db=mock_db,
                )
        assert exc_info.value.status_code == 401
        assert "sb_" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------

class TestAuthSchemas:
    def test_api_key_create_validates_name(self) -> None:
        from pydantic import ValidationError
        from app.api.schemas.auth import APIKeyCreate

        # Valid
        key = APIKeyCreate(name="my-laptop")
        assert key.name == "my-laptop"

        # Empty name rejected
        with pytest.raises(ValidationError):
            APIKeyCreate(name="")

    def test_api_key_response_from_attributes(self) -> None:
        from app.api.schemas.auth import APIKeyResponse

        response = APIKeyResponse(
            id=uuid.uuid4(),
            name="test",
            key_prefix="sb_live_",
            created_at="2026-04-19T00:00:00Z",
            last_used_at=None,
            is_active=True,
        )
        assert response.is_active is True
        assert response.last_used_at is None
