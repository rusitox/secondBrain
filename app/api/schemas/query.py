"""Schemas for the /query endpoint."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class QueryRequest(BaseModel):
    """Request body for POST /query."""

    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Optional filters
    source: Optional[str] = None
    sources: Optional[List[str]] = None
    author: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    @model_validator(mode="after")
    def check_source_fields(self) -> "QueryRequest":
        if self.source and self.sources:
            raise ValueError("Provide either 'source' or 'sources', not both")
        return self


class DocumentSource(BaseModel):
    """A source document referenced in the query response."""

    document_id: str
    content: str
    source: str
    source_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    similarity: float


class QueryResponse(BaseModel):
    """Response from POST /query."""

    answer: str
    sources: List[DocumentSource]
    query: str
