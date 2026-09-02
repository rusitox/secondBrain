# Plan: Agent Memory & Learning Upgrade

**Goal**: Transform the current static, single-turn agent into a conversational agent with
native tool-use, cross-session memory, and the ability to learn from client interactions.

**Date**: 2026-09-02  
**Status**: Implemented — 2026-09-02

---

## Current State

| Dimension | Current |
|---|---|
| Tool selection | Hard-coded in Python (always runs memory + tasks; calendar by keyword) |
| Tool-use | None — Claude receives pre-gathered context, not tool definitions |
| Conversation | Single-turn, stateless — no history between queries |
| Learning | None — no mechanism to extract or persist learnings |
| LLM client | `generate(system, user_message) → str` only |

---

## Target State

| Dimension | Target |
|---|---|
| Tool selection | Claude decides via Anthropic tool-use API |
| Tool-use | Agentic loop: Claude calls tools, gets results, continues reasoning |
| Conversation | Session-scoped history passed on every turn; stored in DB |
| Learning | Claude can call `save_memory`; post-ingestion extractor runs in background |
| LLM client | `generate_with_tools(messages, tools) → structured response` |

---

## Architecture Overview

```
CLI Session (session_id generated at startup)
      │
      ▼
POST /agent/query  {question, session_id}
      │
      ▼
AgentOrchestrator.query(db, user_id, question, session_id)
      │
      ├── Load conversation history (last N turns from conversation_turns)
      │
      ├── LLMClient.generate_with_tools(messages, tool_definitions)
      │        │
      │        │  ┌─────────────────── Agentic Loop (max 5 iterations) ───┐
      │        ├──► Claude → tool_use blocks                              │
      │        │         ↓                                                 │
      │        ├──► Execute tools in parallel                             │
      │        │         ↓                                                 │
      │        ├──► Send tool_results back to Claude                      │
      │        │         ↓                                                 │
      │        └──► Claude → text (no more tool_use) ──────────────────── ┘
      │
      ├── Persist: user turn + assistant turn → conversation_turns
      │
      └── Return {answer, tools_used, sources, session_id}
```

### Tools available to Claude (6 total)

| Tool | Already exists | Description |
|---|---|---|
| `search_memory` | Yes (refactor) | Semantic search over ingested documents |
| `list_tasks` | Yes (refactor) | Pending commitments and action items |
| `get_calendar` | Yes (refactor) | Today's calendar events from Outlook |
| `get_user_style` | Yes (refactor) | User persona and tone guidelines |
| `search_learnings` | **New** | Semantic search over distilled memory entries |
| `save_learning` | **New** | Persist a learning/insight to long-term memory |

---

## Phase 1 — Native Tool-Use Agentic Loop

**Scope**: LLMClient + AgentOrchestrator. No schema changes.

### 1.1 LLMClient: add `generate_with_tools()`

New method on `LLMClient` (Anthropic only for now; OpenAI stub raises NotImplementedError):

```python
async def generate_with_tools(
    self,
    messages: List[Dict],          # [{"role": "user"|"assistant", "content": ...}]
    tools: List[Dict],             # Anthropic tool definitions (JSON schema)
    system: str = "",
    max_iterations: int = 5,
    temperature: float = 0.3,
) -> ToolUseResult:
    """Agentic loop: generate → detect tool_use → execute → send results → repeat."""
    ...
```

Returns a `ToolUseResult` dataclass:
```python
@dataclass
class ToolUseResult:
    final_answer: str
    tool_calls: List[ToolCall]     # all tool calls made across all iterations
    iterations: int
    stop_reason: str               # "end_turn" | "max_iterations"
```

**Loop logic (Anthropic)**:
1. Call `client.messages.create(model, system, messages, tools, tool_choice="auto")`
2. If response has `tool_use` blocks → execute each tool → append `tool_result` to messages → go to 1
3. If response is `text` or `end_turn` → return final answer
4. If `iterations >= max_iterations` → force stop, return last text content

**Key constraint**: The tool execution callbacks are passed into `generate_with_tools` as a dict
`{tool_name: async_callable}`. The LLMClient stays pure (no DB dependency). The orchestrator
provides the callables.

### 1.2 Tool definitions (JSON Schema format for Anthropic)

Each tool:
```python
{
    "name": "search_memory",
    "description": "Search the user's knowledge base (emails, Slack, meeting transcripts, etc.)...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
            "source": {"type": "string", "enum": ["slack", "outlook", "fathom", "teams", "notion"],
                       "description": "Optional: filter by platform"},
            "top_k": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    }
}
```

Tool definitions live in `app/services/agent/tool_definitions.py` (new file).

### 1.3 AgentOrchestrator refactor

Replace `query()` with:
```python
async def query(
    self,
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    session_id: Optional[str] = None,    # new
    conversation_history: Optional[List[Dict]] = None,  # new (Phase 2)
) -> Dict[str, Any]:
```

Orchestrator responsibilities:
1. Build `messages` list (start with user question; prepend history in Phase 2)
2. Build `tool_executors` dict: `{tool_name: partial(tool.run, db=db, user_id=user_id)}`
3. Call `llm_client.generate_with_tools(messages, TOOL_DEFINITIONS, tool_executors)`
4. Return `{answer, tools_used, sources, session_id}`

**Style injection**: `get_user_style` is a tool, but Claude is **instructed to always call it
first** via the system prompt. This ensures every response respects the user's persona and
tone regardless of query type. The instruction reads:
> "Always begin by calling get_user_style to understand how this user communicates.
> Use the result to shape the tone and style of your final answer."

### 1.4 API schema changes

`AgentQueryRequest` adds optional `session_id`:
```python
class AgentQueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # new; UUID string
```

`AgentQueryResponse` adds `session_id`:
```python
class AgentQueryResponse(BaseModel):
    answer: str
    tools_used: List[str]
    sources: List[Dict[str, Any]]
    query: str
    session_id: str                    # new; echoed or newly created
    iterations: int                    # new; how many tool-use rounds
```

---

## Phase 2 — Conversation Memory

**Scope**: New DB table + model, session lifecycle, CLI session_id propagation.

### 2.1 New model: `ConversationTurn`

```
conversation_turns
  id             UUID PK
  session_id     UUID NOT NULL  (no FK — sessions are ephemeral)
  user_id        UUID FK → users.id ON DELETE CASCADE
  role           TEXT NOT NULL   ("user" | "assistant")
  content        TEXT NOT NULL
  tool_calls     JSONB           (serialized ToolCall list, nullable)
  created_at     TIMESTAMP
```

Migration: `009_add_conversation_turns.py`

No `ConversationSession` table — sessions are implicit (grouped by session_id UUID).
Sessions expire after 24h of inactivity. On expiry the session is **archived** (kept in DB,
excluded from active context). A future `/history` command can surface archived sessions.
Enforcement: at query time, if last turn > 24h ago, start fresh and return new session_id.

### 2.2 Session lifecycle

**On each `/agent/query` call:**
1. If `session_id` is None or not found → create new UUID, return it in response
2. If `session_id` exists → load last 20 turns ordered by `created_at`
3. If last turn > 24h ago → treat as new session
4. After generating answer → persist user turn + assistant turn

**Conversation window**: last 20 turns (configurable via `AGENT_CONVERSATION_WINDOW` env var).
Older turns are not deleted, just not included in the active context window.

### 2.3 Message format for Claude

History turns are prepended to the messages list before the current question:
```python
messages = [
    {"role": "user", "content": "What did John say last week?"},
    {"role": "assistant", "content": "Based on the Slack messages..."},
    {"role": "user", "content": "And what about the budget?"},   # ← current question
]
```

Tool calls in history are serialized as assistant content blocks (Anthropic format),
allowing Claude to remember what it looked up in prior turns.

### 2.4 CLI changes

`cli/chat.py`:
- Generate `session_id = str(uuid.uuid4())` once at session start
- Pass `session_id` in every `agent_query()` call
- On first response: print `"Session: {session_id[:8]}..."` (muted)
- `api_client.agent_query()` accepts and passes `session_id`

---

## Phase 3 — Experiential Memory (Learning from client interactions)

**Scope**: New `Memory` model, two new tools, optional background extractor.

### 3.1 New model: `Memory`

```
memories
  id             UUID PK
  user_id        UUID FK → users.id ON DELETE CASCADE
  content        TEXT NOT NULL          (short distilled fact or insight)
  entities       JSONB DEFAULT '[]'     ([{"name": "Acme Corp", "type": "company"}, ...])
  source_type    TEXT                   ("conversation" | "ingestion" | "manual")
  source_ref     TEXT                   (session_id or document source_id)
  importance     SMALLINT DEFAULT 3     (1=low, 5=critical)
  embedding      VECTOR(1536)           (pgvector, same as documents)
  created_at     TIMESTAMP
  updated_at     TIMESTAMP
```

Migration: `010_add_memories_table.py`

### 3.2 New tool: `save_learning`

Claude calls this when it learns something worth remembering about a person, project, or pattern:

```python
# Tool definition
{
    "name": "save_learning",
    "description": (
        "Persist a learning or insight to long-term memory. Use this when you discover "
        "something important about a client, project, or pattern that should be remembered "
        "in future conversations. Examples: client preferences, project constraints, "
        "key decisions made, relationship context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The learning, written as a clear factual statement"},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": ["person", "company", "project", "product"]}
                    }
                },
                "description": "People, companies, or projects this learning is about"
            },
            "importance": {"type": "integer", "minimum": 1, "maximum": 5,
                          "description": "1=trivia, 3=useful, 5=critical"}
        },
        "required": ["content"]
    }
}
```

`SaveLearningTool.run()`:
1. Embed the content
2. Insert into `memories`
3. Return `{"saved": True, "memory_id": "..."}`

### 3.3 New tool: `search_learnings`

```python
{
    "name": "search_learnings",
    "description": (
        "Search long-term memory for insights and learnings about clients, projects, "
        "and patterns. Use this when you need to recall what has been learned about "
        "a specific person, company, or topic across all past conversations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "entity_name": {"type": "string", "description": "Optional: filter by person or company name"},
            "top_k": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    }
}
```

`SearchLearningsTool.run()`:
1. Embed query
2. pgvector cosine similarity search on `memories` table
3. Optional: filter by `entities @> '[{"name": entity_name}]'` (JSONB contains)
4. Return list of `{content, entities, importance, created_at, similarity}`

### 3.3b Memory deduplication

Before inserting a new memory, `SaveLearningTool` checks for near-duplicates:
1. Embed the new content
2. Query `memories` for top-1 by cosine similarity for this user
3. If similarity >= `MEMORY_DEDUP_THRESHOLD` (default 0.92) → skip insert, return existing memory_id
4. Otherwise → insert

This prevents the `memories` table from accumulating semantically equivalent facts over time.

### 3.4 Background learning extractor (optional, post-ingestion)

A `LearningExtractor` service that runs after a batch of new documents is ingested:

```python
class LearningExtractor:
    """Extract distilled learnings from newly ingested content."""

    async def extract_from_documents(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        documents: List[Document],
    ) -> List[Memory]:
        """Use Claude to extract key facts from new documents."""
        ...
```

**When it runs**: Called from `IngestionPipeline.ingest_batch()` after embeddings are stored,
when `LLM_API_KEY` is available. Processes documents in batches of 10.

**What it extracts**: Given a set of new documents (emails, Slack messages, meeting notes),
Claude extracts facts of the form:
- "X said they prefer Y approach to Z"
- "Project P has deadline D"
- "Company C is evaluating vendor V"
- "Person N is the decision-maker for project P"

**Rate limiting**: Max 20 extractions per ingest batch to avoid cost explosion.
Configurable via `LEARNING_EXTRACTION_ENABLED=true` env var (default: false, opt-in).

---

## File Changes Summary

### New files
| File | Purpose |
|---|---|
| `app/services/agent/tool_definitions.py` | Anthropic tool JSON schemas for all 6 tools |
| `app/services/agent/tools/save_learning.py` | SaveLearningTool class |
| `app/services/agent/tools/search_learnings.py` | SearchLearningsTool class |
| `app/models/conversation_turn.py` | ConversationTurn SQLAlchemy model |
| `app/models/memory.py` | Memory SQLAlchemy model |
| `app/services/agent/learning_extractor.py` | LearningExtractor service |
| `alembic/versions/009_add_conversation_turns.py` | Migration |
| `alembic/versions/010_add_memories_table.py` | Migration |
| `tests/unit/test_agent_tool_use.py` | Tool-use loop tests |
| `tests/unit/test_conversation_memory.py` | Conversation turn tests |
| `tests/unit/test_learning_tools.py` | save_learning + search_learnings tests |

### Modified files
| File | Changes |
|---|---|
| `app/services/llm/claude_client.py` | Add `generate_with_tools()`, `ToolUseResult`, `ToolCall` dataclasses |
| `app/services/agent/agent.py` | Full refactor: agentic loop, history loading, turn persistence |
| `app/api/schemas/briefing.py` | Add `session_id`, `iterations` to request/response |
| `app/api/routers/agent.py` | Pass `session_id` through to orchestrator |
| `app/services/ingestion/pipeline.py` | Optionally call `LearningExtractor` after ingest (Phase 3) |
| `cli/chat.py` | Generate and persist `session_id` per CLI session |
| `cli/api_client.py` | Pass `session_id` in `agent_query()` |
| `app/models/__init__.py` | Export new models |

---

## Dependencies

No new packages required. All needed:
- `anthropic >= 0.30` — tool-use already supported at this version
- `pgvector` — already used for document embeddings; reuse for memories
- `sqlalchemy` — existing async ORM

**Env vars added:**
```
AGENT_CONVERSATION_WINDOW=20          # turns kept in active context
AGENT_MAX_TOOL_ITERATIONS=5           # max agentic loop cycles per query
LEARNING_EXTRACTION_ENABLED=true      # background learning extractor (default on)
MEMORY_DEDUP_THRESHOLD=0.92           # cosine similarity above which a memory is considered duplicate
```

---

## Implementation Order

| Phase | Estimated scope | Value delivered |
|---|---|---|
| **1A** — `generate_with_tools()` in LLMClient | ~150 lines | Foundation for everything |
| **1B** — Tool definitions + AgentOrchestrator refactor | ~200 lines | Claude chooses tools dynamically |
| **2A** — `ConversationTurn` model + migration | ~50 lines | History stored |
| **2B** — Session loading + persistence in orchestrator | ~80 lines | Multi-turn conversation works |
| **2C** — CLI session_id propagation | ~30 lines | End-to-end multi-turn |
| **3A** — `Memory` model + migration | ~50 lines | Learning persistence |
| **3B** — `save_learning` + `search_learnings` tools | ~120 lines | Agent can learn and recall |
| **3C** — `LearningExtractor` background service | ~100 lines | Automatic learning from ingestion |

---

## Open Questions for Review

1. **Tool-use and OpenAI**: Should `generate_with_tools()` also support OpenAI tool-use, or only Anthropic for now? OpenAI has a compatible but different API.

2. **Conversation expiry**: 24h session expiry proposed. Should expired sessions be archived (kept in DB but excluded from context) or deleted?

3. **Learning extraction opt-in**: `LEARNING_EXTRACTION_ENABLED` defaults to `false` (cost protection). Should it default to `true` given this is a single-user system?

4. **Memory deduplication**: If Claude calls `save_learning` with a fact that's semantically similar to an existing memory, should we deduplicate? (Could use similarity threshold before inserting.)

5. **System prompt for tool-use**: The current `AGENT_SYSTEM_PROMPT` assumes Claude will synthesize a final answer. With tool-use, Claude sees tool results progressively — the prompt needs rethinking. Specifically, should Claude be instructed to always call `get_user_style` first, or is that left to its discretion?
