"""Unit tests for security module."""
import uuid

import pytest
from fastapi import HTTPException

from app.core.security import get_current_user_id


class TestGetCurrentUserId:
    async def test_valid_uuid_header(self) -> None:
        uid = str(uuid.uuid4())
        result = await get_current_user_id(x_user_id=uid)
        assert result == uuid.UUID(uid)

    async def test_missing_header_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(x_user_id=None)
        assert exc_info.value.status_code == 401
        assert "Missing" in exc_info.value.detail

    async def test_invalid_uuid_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(x_user_id="not-a-uuid")
        assert exc_info.value.status_code == 401
        assert "Invalid" in exc_info.value.detail

    async def test_empty_string_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(x_user_id="")
        assert exc_info.value.status_code == 401
