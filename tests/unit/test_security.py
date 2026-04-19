"""Unit tests for security module."""
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.security import get_current_user_id


class TestGetCurrentUserId:
    async def test_valid_uuid_header(self) -> None:
        uid = str(uuid.uuid4())
        mock_db = AsyncMock()
        result = await get_current_user_id(
            authorization=None, x_user_id=uid, db=mock_db,
        )
        assert result == uuid.UUID(uid)

    async def test_missing_header_raises_401(self) -> None:
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(
                authorization=None, x_user_id=None, db=mock_db,
            )
        assert exc_info.value.status_code == 401
        assert "Missing" in exc_info.value.detail

    async def test_invalid_uuid_raises_401(self) -> None:
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(
                authorization=None, x_user_id="not-a-uuid", db=mock_db,
            )
        assert exc_info.value.status_code == 401
        assert "Invalid" in exc_info.value.detail

    async def test_empty_string_raises_401(self) -> None:
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(
                authorization=None, x_user_id="", db=mock_db,
            )
        assert exc_info.value.status_code == 401
