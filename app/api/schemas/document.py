import uuid
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    user_id: uuid.UUID
    content: str
    source: str = Field(max_length=20)
    source_id: str = ""
    metadata_: Dict[str, Any] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    content: str
    source: str
    source_id: str
    metadata_: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}
