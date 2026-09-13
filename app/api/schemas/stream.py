"""SSE event vocabulary for the agent streaming endpoint (/agent/stream).

These are not FastAPI request/response models — they describe the shape of
each `data:` payload the orchestrator's callback handler emits and the
router forwards over Server-Sent Events. `EVENT_SCHEMAS` maps each event
name to its model, and `/agent/stream`'s `emit()` closure validates every
payload through it before it goes on the wire — the vocabulary is defined
once, and both the router and the tests that check emitted shapes
(tests/unit/test_streaming_callback.py) import this same mapping, so a
renamed or dropped key fails a request instead of silently drifting.

`StopReason` is deliberately a 3-value closed set even though Strands'
own `StopReason` has 12 (cancelled/checkpoint/content_filtered/end_turn/
guardrail_intervened/interrupt/limit_output_tokens/limit_total_tokens/
limit_turns/max_tokens/stop_sequence/tool_use — see
strands/types/event_loop.py). This is a deliberate translation boundary:
the client only ever needs to branch on "clean end" vs. "paused for human
input" vs. "something else, treat as an error" — see
_normalize_stop_reason in strands_orchestrator.py, which does that mapping
before a stop_reason ever reaches this schema, so a value outside the
three the client is contracted to handle can never validate.
"""
from typing import Any, Callable, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

ThinkingCategory = Literal["AGENTE", "HERRAMIENTA", "SISTEMA", "RAZONAMIENTO"]
ThinkingStatus = Literal["active", "done", "error"]
StopReason = Literal["end_turn", "interrupt", "error"]

# A callback handler emits (event_name, data) synchronously — no coroutine
# scheduling, so emission order is exactly call order. See
# app/services/agent/strands_orchestrator.py::_StreamingCallbackHandler for
# why this replaced an async, fire-and-forget contract.
StreamEmitter = Callable[[str, Dict[str, Any]], None]


class SessionEvent(BaseModel):
    """First event of every stream — lets the client route before any token."""

    session_id: str
    turn_id: str


class ThinkingEvent(BaseModel):
    """One row of the "thinking process" panel.

    `category` is assigned server-side from a static tool->category map
    (see _TOOL_CATEGORY in strands_orchestrator.py) — never chosen by the
    model. Re-emitted with the same `id` and status="done" to flip a row to
    complete; category/label are omitted on that second emission since the
    client already has them from the first — EXCEPT for id="reasoning",
    whose repeated `active` emissions each carry only the newest delta
    (`label` is a fragment to append, mirroring how TokenEvent accumulates
    into the answer — resending the full accumulated text on every delta
    would make bytes transferred grow quadratically with reasoning length);
    its terminal `done` emission carries the full accumulated text once, so
    a client that only cares about the final reasoning trace — or one that
    reconnected mid-stream — never has to have replayed every delta.
    """

    id: str
    category: Optional[ThinkingCategory] = None
    label: Optional[str] = None
    status: ThinkingStatus
    detail: Optional[str] = None


class TokenEvent(BaseModel):
    text: str


class ToolResultSSEEvent(BaseModel):
    """A tool call's result, summarized — never the raw tool output, which
    may contain ingested third-party text (email/Slack bodies)."""

    id: str
    tool: str
    ok: bool
    summary: str


class ActionProposedEvent(BaseModel):
    """Emitted right when a propose_action tool call succeeds — the only
    way the client learns an action_id exists at all, since the tool's own
    result never reaches the client (tool_result's `summary` is free text
    for the thinking panel, not meant to be parsed). The client fetches the
    actual artifact via GET /interactions/actions/{id} (see
    app.api.schemas.interactions) before rendering an approve/reject card."""

    id: str


class ErrorEvent(BaseModel):
    detail: str


class DoneEvent(BaseModel):
    session_id: str
    turn_id: str
    stop_reason: StopReason
    iterations: int = 0
    tools_used: List[str] = Field(default_factory=list)
    awaiting: List[str] = Field(default_factory=list)


EVENT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "session": SessionEvent,
    "thinking": ThinkingEvent,
    "token": TokenEvent,
    "tool_result": ToolResultSSEEvent,
    "action_proposed": ActionProposedEvent,
    "done": DoneEvent,
    "error": ErrorEvent,
}
