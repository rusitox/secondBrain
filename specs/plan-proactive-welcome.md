# Plan: Proactive Welcome on CLI Startup

**Date**: 2026-09-02
**Status**: Draft

---

## Goal

When the user starts a CLI chat session, instead of a static stats panel, the agent delivers a
warm, personalised greeting that reviews pending tasks, today's meetings, and offers proactive
advice — powered by the same agentic tool-use loop already used for regular queries.

---

## Scope

- IN: Replace `_show_welcome()` static panel with a live agent-generated greeting
- IN: Reuse the existing `/agent/query` endpoint and `AgentOrchestrator.query()` unchanged
- IN: Render the greeting through the existing Rich display utilities
- OUT: No new endpoint, no new DB table, no new tool, no schema changes
- OUT: No changes to `AgentOrchestrator`, `tool_definitions.py`, or `claude_client.py`
- OUT: No streaming (use the existing blocking response pattern)

---

## Design Decision: Reuse `/agent/query` with a special prompt

**Option A — New dedicated endpoint** (`POST /agent/welcome`)
- Pros: isolated, can have a tighter system prompt
- Cons: new router handler, new schema class, more surface area, violates the minimal-changes
  constraint

**Option B — Reuse `/agent/query` with a special "welcome prompt"** (chosen)
- The welcome is simply a synthetic question that instructs the agent to do a full
  situational review. The existing agentic loop (6 tools, conversation history, tool-use)
  already knows how to call `list_tasks`, `get_calendar`, and `search_learnings`.
- Zero backend changes required.
- The `session_id` generated at CLI startup is already passed with every query, so the
  welcome message becomes turn #1 of the conversation — giving the agent context for the
  rest of the session.

**Welcome prompt (sent as the "question" parameter):**

```
Good morning. I'm starting my work day. Please give me a warm, personalised welcome and a
proactive situational review. Include:
1. A warm greeting and a question about how I'm doing.
2. A summary of my pending and overdue tasks, with specific advice on what to tackle first.
3. A review of today's meetings and how to prepare or optimise my time.
4. Any relevant insights from long-term memory that apply to today.
5. An offer to help with anything specific.
Keep the tone friendly and concise. Respond in the same language you detect from my past
interactions.
```

This prompt is defined as a constant in `cli/chat.py` — no backend changes needed.

---

## Phase 1 — Replace `_show_welcome()` in the CLI

**Complexity**: Low — ~25 lines changed, 0 new files.

### 1.1 Add the welcome prompt constant

File: `cli/chat.py`

Add after the existing imports, before the `ChatSession` class:

```python
_WELCOME_PROMPT = (
    "Good morning. I'm starting my work day. Please give me a warm, personalised welcome "
    "and a proactive situational review. Include:\n"
    "1. A warm greeting and a question about how I am doing.\n"
    "2. A summary of my pending and overdue tasks with specific advice on what to tackle first.\n"
    "3. A review of today's meetings and how to prepare or optimise my time.\n"
    "4. Any relevant insights from long-term memory that apply to today.\n"
    "5. An offer to help with anything specific.\n"
    "Keep the tone friendly and concise."
)
```

### 1.2 Rewrite `_show_welcome()`

File: `cli/chat.py`, method `ChatSession._show_welcome()` (lines 164–199)

Current behaviour:
- Calls `get_user_stats()` to fetch document and commitment counts
- Renders a static `print_panel()` with those numbers

New behaviour:
- Print a compact static banner (app name + user name, no stats fetch) so the terminal
  shows something instantly
- Call `self._api.agent_query(_WELCOME_PROMPT, session_id=self._session_id)` with the
  full agent timeout
- Render the agent's answer with `print_markdown()` (same as regular query answers) inside
  a Rich panel titled "Good morning, {name}"
- On any API/timeout error: fall back to the current static stats panel (keep the existing
  `get_user_stats` code path as the fallback)

Exact replacement logic:

```python
async def _show_welcome(self) -> None:
    """Show personalised agent-generated welcome, falling back to static stats on error."""
    name = self._config.user_name or "there"

    # Instant visual feedback before the agent responds
    console.print()
    print_muted("secondBrain — preparing your daily briefing...")
    console.print()

    try:
        with spinner("Thinking..."):
            result = await self._api.agent_query(
                _WELCOME_PROMPT, session_id=self._session_id
            )
        answer = result.get("answer", "")
        if answer:
            print_panel(answer, title="Good morning, %s" % name, style="blue")
            # Mark session as shown (reuse existing flag)
            self._session_shown = True
        else:
            self._show_static_welcome(name)
    except (httpx.TimeoutException, APIError, Exception):
        logger.debug("Proactive welcome failed, falling back to static panel")
        self._show_static_welcome(name)

    console.print()
```

### 1.3 Extract static fallback into `_show_static_welcome()`

File: `cli/chat.py`

Move the current `_show_welcome()` body into a new private method
`_show_static_welcome(name: str) -> None` so it remains callable from the fallback path.
This is a pure refactor of the existing code — no logic changes.

---

## Phase 2 — (Optional) Timeout tuning

The agent welcome query invokes up to 6 tools and takes 5–15 seconds. The existing
`_AGENT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)` in `api_client.py` covers this.
No change needed.

If the user finds the wait too long in the future, a `max_iterations=3` cap can be passed
as a new optional field on `AgentQueryRequest`. That is out of scope for now.

---

## Files to Modify

| File | Change |
|---|---|
| `cli/chat.py` | Add `_WELCOME_PROMPT` constant; rewrite `_show_welcome()`; add `_show_static_welcome()` |

## Files NOT changed

| File | Why untouched |
|---|---|
| `app/api/routers/agent.py` | Existing `/agent/query` endpoint used as-is |
| `app/services/agent/agent.py` | `AgentOrchestrator.query()` handles the welcome prompt natively |
| `app/api/schemas/briefing.py` | No schema changes |
| `cli/api_client.py` | `agent_query()` already supports `session_id` |
| `cli/display.py` | Existing `print_panel`, `print_markdown`, `spinner`, `print_muted` cover all rendering needs |

---

## Risks & Considerations

| Risk | Mitigation |
|---|---|
| Agent takes 10–15 s to respond on startup | Instant "preparing briefing..." text shown before spinner; fallback if timeout |
| No data yet (new user, no platforms connected) | Agent will say so gracefully; static fallback catches hard errors |
| Welcome persisted as conversation turn #1 | Desirable — gives the agent context for the rest of the session; the synthetic prompt won't confuse because it's a normal user message |
| `_session_shown` flag already set by welcome | Correct — `_handle_query()` won't print the session indicator a second time |
| Language detection | The prompt ends with "Respond in the same language..." — the agent already handles this via `get_user_style` and past conversation history |

---

## Implementation Notes

- The `_WELCOME_PROMPT` constant must be a plain string (no f-string), Python 3.8-compatible.
- The `except Exception` broad catch in `_show_welcome` is intentional — startup must never
  crash due to the welcome query failing. Log at DEBUG level.
- `print_panel(answer, ...)` will render the agent's markdown-formatted answer as plain text
  inside a panel. If richer rendering is preferred, use `console.print(Markdown(answer))`
  without the panel wrapper — decision left to the implementer based on visual preference.
- The `_show_static_welcome()` helper must not be `async` — it performs no I/O.
  The stats call that currently lives in `_show_welcome()` can remain in
  `_show_static_welcome()` as an `await` call, which means `_show_static_welcome` should
  remain `async`. Rename accordingly: `async def _show_static_welcome(name: str) -> None`.
