"""Unit tests for _StreamingCallbackHandler — the synchronous SSE event emitter.

Feeds synthetic Strands callback kwargs (current_tool_use / message /
reasoningText / data, per strands/types/_events.py) and asserts both the
resulting event *shapes* and their exact emission *order* — the property the
previous async fire-and-forget contract (loop.create_task) could not
guarantee once more than one event type existed. See
app/services/agent/strands_orchestrator.py for the rationale.
"""
from typing import Any, Dict, List, Tuple

from app.api.schemas.stream import EVENT_SCHEMAS, DoneEvent, ErrorEvent, SessionEvent
from app.services.agent.strands_orchestrator import (
    _StreamingCallbackHandler,
    _summarize_tool_result,
)


def _recorder() -> Tuple[List[Tuple[str, Dict[str, Any]]], Any]:
    """Return (calls, emit) where `emit` synchronously appends to `calls`."""
    calls: List[Tuple[str, Dict[str, Any]]] = []

    def emit(event: str, data: Dict[str, Any]) -> None:
        calls.append((event, data))

    return calls, emit


class TestToolCallStart:
    def test_emits_active_thinking_step_with_mapped_category(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory"})

        assert calls == [("thinking", {
            "id": "t1", "category": "AGENTE", "label": "search_memory", "status": "active",
        })]
        assert handler.tools_used == ["search_memory"]
        assert handler.iterations == 1

    def test_unmapped_tool_gets_default_category(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"toolUseId": "t1", "name": "some_future_tool"})

        assert calls[0][1]["category"] == "HERRAMIENTA"

    def test_category_is_never_read_from_model_input(self) -> None:
        """Category comes only from the static map, even if the tool input
        smuggled a "category" key — the model must not be able to pick a
        badge color for itself."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={
            "toolUseId": "t1", "name": "search_memory",
            "input": {"category": "RAZONAMIENTO"},
        })

        assert calls[0][1]["category"] == "AGENTE"

    def test_dedupes_repeated_calls_for_same_tool_use_id(self) -> None:
        """Tool input streams incrementally — the same toolUseId fires many
        times as JSON accumulates. Only the first must emit."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory", "input": {}})
        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory", "input": {"query": "a"}})
        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory", "input": {"query": "ab"}})

        assert len(calls) == 1
        assert handler.tools_used == ["search_memory"]
        assert handler.iterations == 1

    def test_distinct_tool_use_ids_each_emit_but_name_recorded_once(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory"})
        handler(current_tool_use={"toolUseId": "t2", "name": "search_memory"})

        assert [c[1]["id"] for c in calls] == ["t1", "t2"]
        assert handler.tools_used == ["search_memory"]
        assert handler.iterations == 2

    def test_missing_tool_use_id_is_ignored(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"name": "search_memory"})

        assert calls == []
        assert handler.tools_used == []
        assert handler.iterations == 0

    def test_empty_current_tool_use_is_ignored(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={})

        assert calls == []


class TestToolResult:
    def test_success_result_emits_tool_result_then_thinking_done(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "get_calendar"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success", "content": [{"json": [1, 2, 3]}],
            }}],
        })

        assert calls == [
            ("tool_result", {"id": "t1", "tool": "get_calendar", "ok": True, "summary": "3 resultados"}),
            ("thinking", {"id": "t1", "status": "done"}),
        ]

    def test_error_result_emits_ok_false_and_thinking_error(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "web_search"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "t1", "status": "error", "content": []}}],
        })

        assert calls == [
            ("tool_result", {"id": "t1", "tool": "web_search", "ok": False, "summary": "error"}),
            ("thinking", {"id": "t1", "status": "error"}),
        ]

    def test_assistant_role_message_is_ignored(self) -> None:
        """ModelMessageEvent's assistant message must not be mistaken for a
        tool result — only user-role messages carry toolResult blocks."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(message={"role": "assistant", "content": [{"text": "hola"}]})

        assert calls == []

    def test_unknown_tool_use_id_yields_empty_tool_name(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(message={
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "unseen", "status": "success", "content": []}}],
        })

        assert calls[0] == ("tool_result", {"id": "unseen", "tool": "", "ok": True, "summary": "completado"})

    def test_successful_propose_action_emits_action_proposed_from_text_block(self) -> None:
        """Regression: Strands' OpenAI provider wraps a dict-returning
        tool's result as {"text": "<json-encoded-str>"}, NOT {"json": {...}}
        — only list-returning tools get a real "json" block. Confirmed
        empirically against a live run; propose_action's dict return value
        (its normal, real-world shape) must still be recognized."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "propose_action"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success",
                "content": [{"text": '{"action_id": "abc-123", "status": "proposed", "risk": "low"}'}],
            }}],
        })

        assert ("action_proposed", {"id": "abc-123"}) in calls

    def test_successful_propose_action_also_recognizes_a_real_json_block(self) -> None:
        """Defensive coverage for the other shape (a real {"json": {...}}
        block) in case a future Strands version — or a different model
        provider — wraps dict results that way instead."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "propose_action"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success",
                "content": [{"json": {"action_id": "abc-123", "status": "proposed", "risk": "low"}}],
            }}],
        })

        assert ("action_proposed", {"id": "abc-123"}) in calls

    def test_idempotent_reproposal_of_an_in_flight_action_still_emits(self) -> None:
        """propose_action's idempotency path returns the SAME action_id
        with whatever its CURRENT status is (approved/executing/executed)
        when an identical payload is re-proposed while an earlier proposal
        is already past "proposed" — not "proposed" itself. Gatekeeping on
        status=="proposed" here would silently drop this case; the
        client's own GET always returns the true status, so this emission
        only needs to hand over the id."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "propose_action"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success",
                "content": [{"text": (
                    '{"action_id": "abc-123", "status": "executing", '
                    '"note": "an identical action was already proposed"}'
                )}],
            }}],
        })

        assert ("action_proposed", {"id": "abc-123"}) in calls

    def test_propose_action_error_result_does_not_emit_action_proposed(self) -> None:
        """propose_action can also return {"error": ...} on a validation
        failure — status is still "success" at the tool-call level (the
        error is business-level, not an exception), so this must key off
        the payload's own "status" field, not the outer tool status."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "propose_action"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success",
                "content": [{"text": '{"error": "invalid payload"}'}],
            }}],
        })

        assert not any(event == "action_proposed" for event, _ in calls)

    def test_other_tools_never_emit_action_proposed(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)
        handler(current_tool_use={"toolUseId": "t1", "name": "get_calendar"})
        calls.clear()

        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success",
                "content": [{"json": {"action_id": "abc-123", "status": "proposed"}}],
            }}],
        })

        assert not any(event == "action_proposed" for event, _ in calls)


class TestReasoning:
    def test_reasoning_text_emits_active_razonamiento_step(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="Priorizando 12 ítems")

        assert calls == [("thinking", {
            "id": "reasoning", "category": "RAZONAMIENTO",
            "label": "Priorizando 12 ítems", "status": "active",
        })]

    def test_reasoning_without_text_falls_through_to_token_check(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="", data="hola")

        assert calls == [("token", {"text": "hola"})]

    def test_active_emissions_carry_only_the_delta_not_the_accumulated_text(self) -> None:
        """Resending the full accumulated text on every delta would make
        bytes transferred grow quadratically with reasoning length — each
        "active" emission must carry just the new fragment. The full text
        is only ever sent once, in the terminal "done" emission (see the
        next test) — a client accumulates deltas the same way it already
        does for `token` events."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="Priorizando ")
        handler(reasoning=True, reasoningText="12 ítems")

        assert [c[1]["label"] for c in calls] == ["Priorizando ", "12 ítems"]

    def test_closes_when_a_tool_call_follows(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="pen")
        handler(reasoning=True, reasoningText="sando")
        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory"})

        assert calls[2] == ("thinking", {"id": "reasoning", "status": "done", "label": "pensando"})
        assert calls[3][1]["id"] == "t1"

    def test_closes_when_answer_tokens_follow(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="pensando")
        handler(data="che")

        assert calls[1] == ("thinking", {"id": "reasoning", "status": "done", "label": "pensando"})
        assert calls[2] == ("token", {"text": "che"})

    def test_resets_after_closing_so_a_new_turn_starts_fresh(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="primero")
        handler(data="che")
        calls.clear()

        handler(reasoning=True, reasoningText="segundo")

        assert calls == [("thinking", {
            "id": "reasoning", "category": "RAZONAMIENTO", "label": "segundo", "status": "active",
        })]


class TestTokens:
    def test_forwards_text_tokens_in_call_order(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(data="hola ")
        handler(data="mundo")

        assert calls == [("token", {"text": "hola "}), ("token", {"text": "mundo"})]

    def test_empty_data_emits_nothing(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(data="")

        assert calls == []

    def test_no_emitter_does_not_raise(self) -> None:
        handler = _StreamingCallbackHandler(None)
        handler(data="token")  # must be a no-op, not an error
        handler(current_tool_use={"toolUseId": "t1", "name": "search_memory"})
        assert handler.tools_used == ["search_memory"]  # tracking still works without an emitter


class TestEmissionOrder:
    def test_realistic_sequence_preserves_call_order(self) -> None:
        """A synchronous emit call preserves order exactly — the property a
        fire-and-forget asyncio.create_task could not guarantee once more
        than one event type existed."""
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(current_tool_use={"toolUseId": "t1", "name": "get_calendar"})
        handler(data="Che, ")
        handler(message={
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"text": "ok"}]}}],
        })
        handler(data="tenés una reunión hoy.")

        assert [c[0] for c in calls] == ["thinking", "token", "tool_result", "thinking", "token"]


class TestSummarizeToolResult:
    def test_list_json_reports_count(self) -> None:
        assert _summarize_tool_result(
            {"status": "success", "content": [{"json": [1, 2]}]}
        ) == "2 resultados"

    def test_single_item_list_is_singular(self) -> None:
        assert _summarize_tool_result(
            {"status": "success", "content": [{"json": [1]}]}
        ) == "1 resultado"

    def test_dict_json_reports_completed(self) -> None:
        assert _summarize_tool_result(
            {"status": "success", "content": [{"json": {"ok": True}}]}
        ) == "completado"

    def test_dict_via_text_block_reports_completed(self) -> None:
        """Regression: a dict-returning tool's result arrives as a
        JSON-encoded string in a "text" block (Strands' real behavior for
        dict returns, confirmed empirically), not a "json" block — without
        parsing that, its raw JSON text leaked into the thinking panel."""
        assert _summarize_tool_result(
            {"status": "success", "content": [{"text": '{"ok": true}'}]}
        ) == "completado"

    def test_text_block_truncated(self) -> None:
        text = "x" * 200
        summary = _summarize_tool_result({"status": "success", "content": [{"text": text}]})
        assert summary.endswith("…")
        assert len(summary) <= 81

    def test_non_success_status_is_error_regardless_of_content(self) -> None:
        assert _summarize_tool_result(
            {"status": "error", "content": [{"json": [1, 2, 3]}]}
        ) == "error"

    def test_success_with_no_recognizable_content_falls_back(self) -> None:
        assert _summarize_tool_result({"status": "success", "content": []}) == "completado"


class TestEmittedEventsMatchSchema:
    """Contract test: every event shape the handler and the /agent/stream
    router actually build must validate against app.api.schemas.stream —
    otherwise that module's stated single-source-of-truth is not enforced by
    anything and either side is free to drift (rename/drop a key) without
    mypy or a test ever catching it."""

    def test_handler_emitted_shapes(self) -> None:
        calls, emit = _recorder()
        handler = _StreamingCallbackHandler(emit)

        handler(reasoning=True, reasoningText="pensando")
        handler(current_tool_use={"toolUseId": "t1", "name": "get_calendar"})
        handler(message={
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"json": [1]}]}}],
        })
        handler(current_tool_use={"toolUseId": "t2", "name": "propose_action"})
        handler(message={
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": "t2", "status": "success",
                "content": [{"json": {"action_id": "abc-123", "status": "proposed", "risk": "low"}}],
            }}],
        })
        handler(data="hola")

        assert calls, "handler produced no events to validate"
        for event_name, data in calls:
            EVENT_SCHEMAS[event_name](**data)

    def test_router_only_shapes(self) -> None:
        """session/done/error are built in app/api/routers/agent.py, not by
        the handler — validated here against the exact keys that source
        constructs (see agent_stream's emit("session"/"done"/"error", ...) calls)."""
        SessionEvent(session_id="s1", turn_id="t1")
        DoneEvent(
            session_id="s1", turn_id="t1", stop_reason="interrupt",
            iterations=2, tools_used=["search_memory"], awaiting=["interaction-1"],
        )
        ErrorEvent(detail="Agent query failed. Please try again.")
