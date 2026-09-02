import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration, Platform
from app.api.schemas.integration import IntegrationCreate, IntegrationUpdate
from app.utils.encryption import encrypt_token, decrypt_token


async def create_integration(db: AsyncSession, data: IntegrationCreate) -> Integration:
    integration = Integration(
        id=uuid.uuid4(),
        user_id=data.user_id,
        platform=data.platform,
        access_token=encrypt_token(data.access_token),
        refresh_token=encrypt_token(data.refresh_token),
    )
    db.add(integration)
    await db.flush()
    await db.refresh(integration)
    return integration


async def get_integration(
    db: AsyncSession, integration_id: uuid.UUID
) -> Optional[Integration]:
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id)
    )
    return result.scalar_one_or_none()


async def list_integrations(
    db: AsyncSession,
    user_id: uuid.UUID,
    platform: Optional[Platform] = None,
) -> List[Integration]:
    query = select(Integration).where(Integration.user_id == user_id)
    if platform is not None:
        query = query.where(Integration.platform == platform)
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_integration(
    db: AsyncSession, integration: Integration, data: IntegrationUpdate
) -> Integration:
    if data.is_active is not None:
        integration.is_active = data.is_active
    if data.access_token is not None:
        integration.access_token = encrypt_token(data.access_token)
    if data.refresh_token is not None:
        integration.refresh_token = encrypt_token(data.refresh_token)
    await db.flush()
    await db.refresh(integration)
    return integration


async def delete_integration(db: AsyncSession, integration: Integration) -> None:
    await db.delete(integration)
    await db.flush()


def get_decrypted_token(integration: Integration) -> str:
    """Decrypt access token for use in connectors. Never expose via API."""
    return decrypt_token(integration.access_token)


def get_decrypted_user_token(integration: Integration) -> Optional[str]:
    """Decrypt user_token if one is stored. Returns None when not set."""
    if not integration.user_token:
        return None
    return decrypt_token(integration.user_token)


async def set_user_token(
    db: AsyncSession, integration: Integration, user_token: str
) -> Integration:
    """Encrypt and persist a user_token on an existing integration."""
    integration.user_token = encrypt_token(user_token)
    await db.flush()
    await db.refresh(integration)
    return integration
