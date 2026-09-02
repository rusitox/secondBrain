import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.integration import Platform


class IntegrationCreate(BaseModel):
    user_id: uuid.UUID
    platform: Platform
    access_token: str
    refresh_token: str = ""


class IntegrationUpdate(BaseModel):
    is_active: Optional[bool] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class UserTokenRequest(BaseModel):
    user_token: str


class IntegrationRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    platform: Platform
    last_sync_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
