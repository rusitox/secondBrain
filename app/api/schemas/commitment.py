import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.commitment import CommitmentStatus


class CommitmentCreate(BaseModel):
    user_id: uuid.UUID
    document_id: Optional[uuid.UUID] = None
    commitment_text: str
    owner: str = "unknown"
    due_date: Optional[datetime] = None
    priority: int = Field(default=3, ge=1, le=5)


class CommitmentUpdate(BaseModel):
    status: Optional[CommitmentStatus] = None
    due_date: Optional[datetime] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)


class CommitmentRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    commitment_text: str
    owner: str
    due_date: Optional[datetime]
    status: CommitmentStatus
    priority: int
    notion_page_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
