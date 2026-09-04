---
name: Agent Memory Upgrade Review
description: Tool-use agent loop, Memory/ConversationTurn models, save_learning, search_learnings, learning_extractor, migrations 009-010
type: project
---

Phase "agent memory upgrade" code review completed on 2026-09-02. Key findings:

**Criticals fixed before ship:**
- `save_learning.py`: `db.flush()` without `db.commit()` — memory rows lost if request session rolls back. Depends on `get_db()` transaction contract.
- `learning_extractor.py:99`: `.format(documents=...)` with user content — prompt injection, 5th consecutive recurrence of this pattern.
- `memory.py`: ORM `default=list` without `server_default="[]"` — DB constraint violation on raw SQL inserts (same mismatch pattern as Phase 3).
- `agent.py router`: `lru_cache` singleton holds `AsyncOpenAI`/`AsyncAnthropic` clients — stale event loop reference on uvicorn `--reload`.

**Warnings:**
- `ConversationTurn` table (migration 009) and model exist but `agent.query()` never writes rows — feature is dead code.
- `conversation_turn.py`: FK to `users.id` declared in migration but NOT in ORM model — cascade broken, `create_all` will omit FK.
- `claude_client.py:201`: Anthropic SDK `ContentBlock` objects appended to `messages` list (typed as `List[Dict]`) — JSON serialization crash if messages ever serialized.
- `search_learnings.py` JSONB `contains` filter: case-sensitive entity matching silently misses entries.
- migrations 009/010: `id` UUID column has no `server_default` — raw SQL inserts fail.
- Bare `except Exception` in learning_extractor — 13th+ recurrence.

**Recurring systemic patterns (now at these counts):**
1. Prompt injection via `.format()` with external content: 5 phases (4, 5, 6, 9D, agent-memory)
2. ORM `default` without matching `server_default`: Phases 3 and agent-memory
3. Bare `except Exception` swallowing `CancelledError`: 13+ occurrences across codebase
4. Async client singleton in `lru_cache` across event loops: Phases 7A, agent-memory

**Why:** These are now confirmed systemic. A codebase-wide sweep of all `.format(` calls in LLM prompts and all `except Exception` blocks is warranted.

**How to apply:** Flag any new `.format(` usage on LLM prompts as CRITICAL immediately. Check `server_default` whenever a model uses `default=` on non-nullable columns.
