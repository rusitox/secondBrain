"""Style analyzer tool — retrieve user's persona and tone guidelines."""
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Identity

logger = logging.getLogger(__name__)


class StyleAnalyzerTool:
    """Retrieves the user's communication style and persona."""

    name: str = "style_analyzer"
    description: str = (
        "Get the user's communication persona, tone guidelines, and heuristics. "
        "Use this to match the user's style when generating responses."
    )

    async def get_style(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Fetch the user's identity/style profile."""
        result = await db.execute(
            select(Identity).where(Identity.user_id == user_id)
        )
        identity = result.scalar_one_or_none()

        if not identity:
            return {
                "persona_description": "",
                "tone_guidelines": "",
                "heuristics": {},
            }

        return {
            "persona_description": identity.persona_description or "",
            "tone_guidelines": identity.tone_guidelines or "",
            "heuristics": identity.heuristics or {},
        }
