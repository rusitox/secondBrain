"""notion_publish executor — wraps the existing NotionPublisher, the only
real external write capability the system has today (see
app/services/notion/publisher.py). Registers itself on import; see
app.services.actions.registry's module docstring for why nothing but
app/main.py (at startup) ever imports this module.
"""
import logging
import uuid
from typing import Any, Dict, Literal, Optional, Type

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration, Platform
from app.models.user import User
from app.services import integration_service
from app.services.actions.registry import register
from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.publisher import NotionPublisher

logger = logging.getLogger(__name__)


class NotionPublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["briefing"]
    text: str = Field(max_length=8000)
    date_str: str = Field(max_length=40)


class NotionPublishExecutor:
    action_type = "notion_publish"
    version = "1"
    # Declared as the Protocol's own type (not Type[NotionPublishPayload])
    # so this satisfies ActionExecutor structurally — Protocol attributes
    # are checked invariantly, so a narrower declared type would fail
    # mypy even though the assigned value is a valid subclass.
    payload_model: Type[BaseModel] = NotionPublishPayload
    risk = "low"

    async def execute(
        self, db: AsyncSession, user_id: uuid.UUID, payload: BaseModel,
    ) -> Dict[str, Any]:
        assert isinstance(payload, NotionPublishPayload)

        user = await db.get(User, user_id)
        if user is None or not user.notion_config:
            return {"error": "Notion workspace not configured for this user"}
        ws_config = NotionWorkspaceConfig.from_dict(user.notion_config)
        if not ws_config.briefings_db_id:
            return {"error": "Notion workspace has no briefings database"}

        integ = await self._find_active_notion_integration(db, user_id)
        if integ is None:
            return {"error": "No active Notion integration for this user"}
        token = integration_service.get_decrypted_token(integ)

        publisher = NotionPublisher(token, ws_config)
        try:
            page_id = await publisher.publish_briefing(payload.text, payload.date_str)
        except (httpx.HTTPError, RuntimeError) as e:
            logger.warning("notion_publish executor failed for user=%s: %s", user_id, e)
            return {"error": str(e)}

        return {"page_id": page_id}

    @staticmethod
    async def _find_active_notion_integration(
        db: AsyncSession, user_id: uuid.UUID,
    ) -> Optional[Integration]:
        result = await db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == Platform.NOTION,
                Integration.is_active == True,  # noqa: E712
            )
        )
        return result.scalars().first()


register(NotionPublishExecutor())
