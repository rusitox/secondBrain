---
name: Agent memory upgrade — Phase 2
description: ConversationTurn model, migration 009, and CLI session_id propagation added in Phase 2
type: project
---

ConversationTurn model and migration landed in Phase 2 of the agent memory upgrade.

**Why:** Persist every agent interaction turn so future phases can load conversation history and give the agent memory across queries within a session.

**How to apply:** When implementing agent-side history loading (Phase 3+), query `conversation_turns` filtered by `(user_id, session_id)` ordered by `created_at`. The CLI generates a fresh `session_id` UUID per `ChatSession` instance and passes it on every `agent_query()` call.

Key implementation details:
- Model: `app/models/conversation_turn.py` — `ConversationTurn(UUIDMixin, TimestampMixin, Base)`, indexes on `(user_id, session_id)` and `(session_id, created_at)`.
- Migration: `alembic/versions/009_add_conversation_turns.py`, chains from `008`.
- `session_id` stored as `UUID` type in DB; passed as a string from CLI to API.
- `tool_calls` column is `JSONB` nullable — stores serialized ToolCall list for future use.
- CLI announces session UUID once (muted) after the first successful response (`_session_announced` guard).
- `APIClient.agent_query()` accepts `session_id: Optional[str] = None` and includes it in the POST body when present.
- Latest migration revision: `009` (down_revision `008`). Next migration must use `down_revision = "009"`.
