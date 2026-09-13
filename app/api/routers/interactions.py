"""Interactions API — answering structured requests the agent raised via
request_user_input (see app/services/agent/strands_orchestrator.py and
app/services/agent/interactions_store.py).

POST /interactions/{interaction_id}/answer — submit the human's answer and
resume the paused agent turn, streamed via Server-Sent Events using the
same event vocabulary as /agent/stream (app.api.schemas.stream), so the
client has exactly one streaming code path regardless of whether a turn
started fresh or resumed from an interrupt.
"""
import asyncio
import json as json_module
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_db
from app.api.routers.agent import _get_agent
from app.api.schemas.interactions import InteractionDetailResponse, ProposedActionDetailResponse
from app.api.schemas.stream import EVENT_SCHEMAS
from app.models.proposed_action import ActionStatus, ProposedAction
from app.services.actions import store as actions_store
from app.services.actions.registry import get as get_executor
from app.services.agent import interactions_store
from app.services.agent.knowledge.answer import apply_learn_directive
from app.services.agent.strands_orchestrator import SnapshotUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interactions", tags=["interactions"])


class AnswerInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Dict[str, Any] = Field(
        ..., description="field_key -> value, matching the interaction's spec.fields",
    )


def _validate_answer(spec: Dict[str, Any], answer: Dict[str, Any]) -> List[str]:
    """Check the submitted answer against each field's own kind-specific
    contract (app.api.schemas.ui_protocol.UIField), not just key presence.

    This matters beyond form correctness: a `learn` directive feeds an
    answer value straight into a knowledge-graph claim at
    CONFIRMED_BY_USER/1.0 confidence (apply_learn_directive), and an
    unvalidated value would otherwise reach that with no check that it was
    even one of the options the field declared.
    """
    errors: List[str] = []
    fields = spec.get("fields", [])
    if not isinstance(fields, list):
        return errors

    for f in fields:
        if not isinstance(f, dict):
            continue
        key = f.get("key")
        kind = f.get("kind")
        required = f.get("required", True)

        if key not in answer:
            if required:
                errors.append(f"missing required field: {key}")
            continue

        value = answer[key]
        option_ids: set = {
            o["id"] for o in f.get("options", []) or [] if isinstance(o, dict) and o.get("id") is not None
        }

        if kind in ("single_select", "entity_pick"):
            allow_none = f.get("allow_none", False)
            if value is None and allow_none:
                continue
            if not isinstance(value, str) or value not in option_ids:
                errors.append(f"{key}: value must be one of {sorted(option_ids)}")
        elif kind == "multi_select":
            if not isinstance(value, list) or not all(isinstance(v, str) and v in option_ids for v in value):
                errors.append(f"{key}: value must be a list of {sorted(option_ids)}")
            else:
                min_select, max_select = f.get("min_select"), f.get("max_select")
                if min_select is not None and len(value) < min_select:
                    errors.append(f"{key}: requires at least {min_select} selection(s)")
                if max_select is not None and len(value) > max_select:
                    errors.append(f"{key}: allows at most {max_select} selection(s)")
        elif kind == "confirm":
            if not isinstance(value, bool):
                errors.append(f"{key}: value must be a boolean")
        elif kind == "text":
            if not isinstance(value, str):
                errors.append(f"{key}: value must be a string")
            else:
                max_length = f.get("max_length")
                if max_length is not None and len(value) > max_length:
                    errors.append(f"{key}: exceeds max_length={max_length}")
        # datetime: not deeply validated here — left to the client's own
        # picker and, eventually, the consuming tool.

    return errors


@router.get("/{interaction_id}", response_model=InteractionDetailResponse)
async def get_interaction(
    interaction_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> InteractionDetailResponse:
    """Fetch the full UIRequest spec for an interaction the client only
    knows the id of (from `done.awaiting` — see app.api.schemas.stream).
    Readable regardless of status (open/answered/expired/cancelled): a
    client re-rendering a past turn needs to show what was asked and, if
    answered, what the human said — not just open ones."""
    interaction = await interactions_store.get_interaction(db, current_user_id, interaction_id)
    if interaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interaction not found")
    return InteractionDetailResponse(
        id=interaction.id,
        status=interaction.status.value,
        spec=interaction.spec,
        answer=interaction.answer,
        expires_at=interaction.expires_at,
    )


@router.post("/{interaction_id}/answer")
async def answer_interaction(
    interaction_id: uuid.UUID,
    data: AnswerInteractionRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> "EventSourceResponse":  # type: ignore[name-defined]
    """Answer an open interaction and resume the agent turn it paused.

    Two-step so a malformed answer doesn't burn the human's one shot at
    answering: peek at the interaction and validate the answer against
    each field's own kind-specific contract WITHOUT transitioning its
    status, then claim it (open -> answered) only once it's structurally
    valid. The claim itself is still the sole source of the idempotency
    guarantee — a concurrent double-submit is rejected there (409), not by
    this check.

    Events emitted: same vocabulary as /agent/stream (session, thinking,
    token, tool_result, done, error) — see that endpoint's docstring.
    """
    interaction = await interactions_store.get_interaction(db, current_user_id, interaction_id)
    if interaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interaction not found")
    if interaction.status.value != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Interaction is already {interaction.status.value}",
        )
    errors = _validate_answer(interaction.spec, data.answer)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    claimed = await interactions_store.claim_interaction_for_answer(
        db, current_user_id, interaction_id, data.answer, answered_via="ui",
    )
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interaction was answered or expired by the time this request completed",
        )

    # Explicit, typed opt-in only (app.api.schemas.ui_protocol.LearnDirective)
    # — answering an interaction otherwise never touches the knowledge
    # graph. Applied before the resume/commit below so the claim lands even
    # if the subsequent LLM resume fails.
    await apply_learn_directive(db, current_user_id, claimed.spec, data.answer)

    # Committed before resuming: the claim must be durable before we start
    # a potentially long LLM-driven resume, so a crash mid-resume never
    # leaves the interaction re-answerable.
    await db.commit()

    session_id = claimed.session_id
    interrupt_id = claimed.interrupt_id
    answer_values = data.answer

    from sse_starlette.sse import EventSourceResponse

    async def event_generator() -> AsyncIterator[dict]:
        queue: "asyncio.Queue[Any]" = asyncio.Queue()
        SENTINEL = object()

        def emit(event: str, event_data: Dict[str, Any]) -> None:
            # See app/api/routers/agent.py's emit() for why this is
            # synchronous and why it validates through EVENT_SCHEMAS.
            validated = EVENT_SCHEMAS[event](**event_data).model_dump(exclude_none=True)
            queue.put_nowait({"event": event, "data": json_module.dumps(validated)})

        async def run_resume() -> None:
            try:
                agent_inst = _get_agent()
                result = await agent_inst.resume(
                    db=db,
                    user_id=current_user_id,
                    session_id=session_id,
                    interrupt_id=interrupt_id,
                    answer_values=answer_values,
                    emit=emit,
                )
                emit("done", {
                    "session_id": result.get("session_id", ""),
                    "turn_id": result.get("turn_id", ""),
                    "stop_reason": result.get("stop_reason", "end_turn"),
                    "iterations": result.get("iterations", 0),
                    "tools_used": result.get("tools_used", []),
                    "awaiting": result.get("awaiting", []),
                })
            except asyncio.CancelledError:
                raise
            except SnapshotUnavailableError as e:
                logger.warning("Interaction resume failed — no live snapshot: %s", e)
                emit("error", {"detail": "This conversation can no longer be resumed."})
            except Exception as e:
                # Deliberately broad: a narrower tuple here (as this
                # endpoint originally had) misses anything Strands' own
                # snapshot/interrupt deserialization can raise (e.g. a
                # KeyError from _InterruptState.resume() on a mismatched
                # interrupt id) and SQLAlchemyError from the DB writes in
                # _finalize_turn's interrupt branch — any of which would
                # otherwise propagate past this generator, so the SSE
                # stream just closes with no "error" event and the client
                # never learns why.
                logger.exception("Interaction resume error: %s", e)
                emit("error", {"detail": "Agent query failed. Please try again."})
            finally:
                await queue.put(SENTINEL)

        task = asyncio.create_task(run_resume())

        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return EventSourceResponse(event_generator())


class ApproveActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_sha256: str = Field(
        ..., description="Echoes the payload hash shown for this action — binds approval to the exact bytes reviewed",
    )


@router.get("/actions/{action_id}", response_model=ProposedActionDetailResponse)
async def get_proposed_action(
    action_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ProposedActionDetailResponse:
    """Fetch a proposed action's preview artifact — the client only learns
    an action_id exists via the `action_proposed` SSE event (see
    app.api.schemas.stream); this is where it gets the actual artifact to
    render, and the payload_sha256 it must echo back to approve it."""
    action = await db.get(ProposedAction, action_id)
    if action is None or action.user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    return ProposedActionDetailResponse(
        id=action.id,
        action_type=action.action_type,
        status=action.status.value,
        risk=action.risk,
        artifact=action.artifact,
        payload_sha256=action.payload_sha256,
        expires_at=action.expires_at,
        error=action.error,
    )


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: uuid.UUID,
    data: ApproveActionRequest,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Approve a proposed action and execute it.

    This is the only path from "the model proposed this" to "it actually
    ran" — see app.services.actions.registry's module docstring. No LLM is
    in this call path: the payload was fixed at propose_action time, the
    hash check below re-verifies it against what the client is approving,
    and the executor runs a plain async function against a validated,
    typed payload.
    """
    action = await db.get(ProposedAction, action_id)
    if action is None or action.user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    if action.status != ActionStatus.PROPOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Action is already {action.status.value}",
        )
    if action.payload_sha256 != data.payload_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payload hash mismatch — re-fetch the action before approving",
        )

    executor = get_executor(action.action_type)
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"action_type={action.action_type!r} is no longer available",
        )

    claimed = await actions_store.claim_action_for_approval(db, current_user_id, action_id)
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action was already approved/rejected or has expired",
        )
    await actions_store.write_audit(db, action_id, event="approved", actor="user")
    await db.commit()

    # If the process crashes between this commit and executor.execute()
    # finishing, whether the real-world side effect (e.g. a Notion write)
    # actually happened is still unknown and unrecoverable via this API —
    # but the row itself no longer gets stuck in EXECUTING forever:
    # app/services/actions/sweeper.py's ActionSweeper marks it FAILED
    # after a grace period so a human can see it happened and decide
    # whether to re-propose.
    await actions_store.mark_executing(db, action_id)
    await db.commit()

    try:
        payload_obj = executor.payload_model(**claimed.payload)
        result = await executor.execute(db, current_user_id, payload_obj)
    except Exception as e:
        logger.exception("Action execution raised for action_id=%s: %s", action_id, e)
        await actions_store.mark_failed(db, action_id, str(e))
        await actions_store.write_audit(db, action_id, event="failed", actor="system", detail={"error": str(e)})
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Action execution failed")

    if "error" in result:
        await actions_store.mark_failed(db, action_id, str(result["error"]))
        await actions_store.write_audit(db, action_id, event="failed", actor="system", detail=result)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(result["error"]))

    await actions_store.mark_executed(db, action_id, result)
    await actions_store.write_audit(db, action_id, event="executed", actor="system", detail=result)
    await db.commit()

    return {"action_id": str(action_id), "status": "executed", "result": result}


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Decline a proposed action. The other terminal path besides approve
    — without it, ActionStatus.REJECTED existed only as an enum value and
    a hypothetical 409 message, unreachable from any endpoint.
    """
    action = await db.get(ProposedAction, action_id)
    if action is None or action.user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")

    rejected = await actions_store.reject_action(db, current_user_id, action_id)
    if rejected is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action is already {action.status.value}",
        )
    await actions_store.write_audit(db, action_id, event="rejected", actor="user")
    await db.commit()

    return {"action_id": str(action_id), "status": "rejected"}
