from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Human label for this key")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    api_key: str
    user_name: str


class APIKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class APIKeyCreated(APIKeyResponse):
    """Returned only once at creation time — includes the full plaintext key."""
    key: str


class APIKeyList(BaseModel):
    keys: List[APIKeyResponse]
