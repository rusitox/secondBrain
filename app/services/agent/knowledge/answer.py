"""Supporting helpers for the generative-UI interaction/learn flow.

Resolving a knowledge-graph PendingQuestion (the confirm_pending_answer
Strands tool) is handled by app.services.agent.knowledge.reconciliation's
apply_question_answer — this module used to duplicate that logic under a
different name; it now only carries what's genuinely unique to the
interactions inbox (app/api/routers/interactions.py): recording a claim
straight from an answered UserInteraction (no PendingQuestion involved),
and rendering a learn directive's claim template.
"""
import logging
import re
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity_claim import ClaimStatus
from app.services.agent.knowledge import reconciliation
from app.services.agent.knowledge import store as knowledge_store

logger = logging.getLogger(__name__)

# Mirrors app.api.schemas.ui_protocol's _TEMPLATE_KEY_PATTERN — kept as a
# separate constant rather than imported, since this one drives runtime
# substitution while that one drives parse-time validation; they must
# agree on the token shape, not share an import across a schema/service
# boundary.
_TEMPLATE_KEY_PATTERN = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")


async def record_user_claim(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_id: uuid.UUID,
    claim_text: str,
) -> Dict[str, Any]:
    """Write a user-confirmed claim directly — no PendingQuestion involved.

    Used by the generative UI protocol's optional ``learn`` directive
    (app.api.schemas.ui_protocol.LearnDirective) when answering a
    UserInteraction should also be captured as durable knowledge. Reuses
    the same claim shape and confidence-recompute step as
    answer_pending_question's knowledge-base branch, but there is no
    question row here to resolve — the interaction row it came from lives
    in a separate table entirely (see app/models/user_interaction.py).
    """
    try:
        async with db.begin_nested():
            await knowledge_store.add_claim(
                db, entity_id, user_id, source="user", claim_text=claim_text,
                asserted_by_agent="user", status=ClaimStatus.CONFIRMED_BY_USER, confidence=1.0,
            )
            new_confidence = await reconciliation.recompute_confidence(db, user_id, entity_id)
            await knowledge_store.update_entity_confidence(db, user_id, entity_id, new_confidence)
    except (SQLAlchemyError, ValueError) as e:
        logger.warning("record_user_claim failed for entity_id=%s: %s", entity_id, e)
        return {"error": str(e)}

    return {"recorded": True, "entity_id": str(entity_id)}


def _render_claim_template(template: str, answer: Dict[str, Any]) -> str:
    """Fill a LearnDirective.claim_template's {field_key} tokens from an
    interaction's answer values.

    Deliberately not str.format()/format_map(): those interpret Python's
    format-spec mini-language, more surface than a fixed-token
    substitution needs for text that ends up as a stored knowledge-graph
    claim. Only ever replaces an exact {lowercase_key} token — anything
    that doesn't match (a stray brace, a key that isn't in `answer`) is
    left as literal text / substituted with an empty string rather than
    raising, since by the time this runs the template has already passed
    UIRequestContent's "references only known field keys" validation.
    """
    def _sub(match: "re.Match[str]") -> str:
        return str(answer.get(match.group(1), ""))
    return _TEMPLATE_KEY_PATTERN.sub(_sub, template)


async def apply_learn_directive(
    db: AsyncSession,
    user_id: uuid.UUID,
    spec: Dict[str, Any],
    answer: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """If `spec` (a stored UIRequest dict) carries a `learn` directive
    (app.api.schemas.ui_protocol.LearnDirective), render its claim_template
    from `answer` and record it via record_user_claim.

    Returns None when there's no directive (the common case, and the only
    way an interaction answer touches the knowledge graph is if the model
    explicitly asked for it — see LearnDirective's docstring) or the
    directive's entity_id isn't a valid UUID; otherwise record_user_claim's
    result dict.
    """
    learn = spec.get("learn")
    if not isinstance(learn, dict):
        return None
    try:
        entity_id = uuid.UUID(str(learn.get("entity_id")))
    except (ValueError, TypeError, AttributeError):
        logger.warning("apply_learn_directive: invalid entity_id=%r in learn directive", learn.get("entity_id"))
        return None
    claim_text = _render_claim_template(str(learn.get("claim_template", "")), answer)
    return await record_user_claim(db, user_id, entity_id, claim_text)
