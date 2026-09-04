---
name: Agent memory upgrade — Phase 1 (tool-use loop)
description: AgentOrchestrator migrated from static pre-gather to Anthropic tool-use agentic loop; LLMClient gained generate_with_tools(); session_id + iterations added to API contract
type: project
---

Phase 1 of the agent memory upgrade is complete and fully rebuilt (2026-09-02). All 44 tests pass after a git stash recovery session that required rebuilding all modified files.

**What changed:**

- `app/services/llm/claude_client.py` — added `ToolCall` and `ToolUseResult` dataclasses; new `generate_with_tools()` method on `LLMClient` runs the Anthropic tool-use loop (up to `max_iterations=5`). Internal retry logic extracted into `_call_anthropic_with_retry()`. OpenAI provider raises `NotImplementedError`. `generate()` is unchanged.
- `app/services/agent/tool_definitions.py` (new) — `AGENT_TOOLS` list with 4 Anthropic-format tool definitions: `search_memory`, `list_tasks`, `get_calendar`, `get_user_style`. Phase 3 stubs (`search_learnings`, `save_learning`) are commented-out.
- `app/services/agent/agent.py` — `AgentOrchestrator` fully rewritten. Static pre-gather pattern replaced by Claude deciding which tools to call. `_format_style()` and `_build_context()` removed. `query()` now accepts `session_id` and `conversation_history`. Tool executors are closures bound to `db` + `user_id` per request. `self._claude` renamed to `self._llm`; constructor accepts `LLMClient` (alias `ClaudeClient` kept for backward compat).
- `app/api/schemas/briefing.py` — `AgentQueryRequest` gained `session_id: Optional[str]`; `AgentQueryResponse` gained `session_id: str` and `iterations: int`.
- `app/api/routers/agent.py` — passes `session_id` through to orchestrator; response includes `session_id` and `iterations`.

**Why:** Anthropic tool-use lets Claude decide which tools to call rather than always running all tools; enables multi-step reasoning and sets up Phase 2 (conversation memory / session history) and Phase 3 (learnings store).

**How to apply:** When touching the agent layer, prefer adding new tools to `AGENT_TOOLS` + registering an executor in `_make_*` factory methods rather than adding pre-gather logic.

**Test DB note:** `tests/conftest.py` has a manual SQLite DDL list in `_create_sqlite_tables()`. New models must have their table DDL added there (including drop order in `_drop_sqlite_tables`). The `conversation_turns` table uses `TEXT` for `tool_calls` (not JSONB) since SQLite doesn't support JSONB. The integration tests query `session_id` as UUID hex via raw SQL.

**OpenAI tool-use:** `_generate_with_tools_openai()` converts Anthropic `input_schema` → OpenAI `parameters`, uses `max_completion_tokens` (not `max_tokens`), and sets `reasoning_effort="none"` when tools are present. The plain `_generate_openai()` also uses `max_completion_tokens`.
