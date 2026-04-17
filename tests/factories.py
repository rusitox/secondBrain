import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from app.models.commitment import Commitment, CommitmentStatus
from app.models.document import Document
from app.models.identity import Identity
from app.models.integration import Integration, Platform
from app.models.user import User


def make_user(
    *,
    email: str = "test@example.com",
    full_name: str = "Test User",
    timezone_: str = "UTC",
) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        full_name=full_name,
        timezone=timezone_,
    )


def make_identity(
    *,
    user_id: uuid.UUID,
    persona_description: str = "A professional assistant",
    tone_guidelines: str = "Be concise and clear",
    heuristics: Optional[Dict] = None,
) -> Identity:
    return Identity(
        id=uuid.uuid4(),
        user_id=user_id,
        persona_description=persona_description,
        tone_guidelines=tone_guidelines,
        heuristics=heuristics or {},
    )


def make_integration(
    *,
    user_id: uuid.UUID,
    platform: Platform = Platform.SLACK,
    access_token: str = "test-token",
    refresh_token: str = "test-refresh",
    is_active: bool = True,
) -> Integration:
    return Integration(
        id=uuid.uuid4(),
        user_id=user_id,
        platform=platform,
        access_token=access_token,
        refresh_token=refresh_token,
        is_active=is_active,
    )


def make_document(
    *,
    user_id: uuid.UUID,
    content: str = "Sample document content",
    source: str = "slack",
    source_id: str = "",
    metadata_: Optional[Dict] = None,
) -> Document:
    return Document(
        id=uuid.uuid4(),
        user_id=user_id,
        content=content,
        source=source,
        source_id=source_id or str(uuid.uuid4()),
        metadata_=metadata_ or {},
    )


def make_commitment(
    *,
    user_id: uuid.UUID,
    document_id: Optional[uuid.UUID] = None,
    commitment_text: str = "Send the report by Friday",
    owner: str = "unknown",
    due_date: Optional[datetime] = None,
    status: CommitmentStatus = CommitmentStatus.PENDING,
    priority: int = 3,
) -> Commitment:
    return Commitment(
        id=uuid.uuid4(),
        user_id=user_id,
        document_id=document_id,
        commitment_text=commitment_text,
        owner=owner,
        due_date=due_date or datetime.now(timezone.utc),
        status=status,
        priority=priority,
    )
