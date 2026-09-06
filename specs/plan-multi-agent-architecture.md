# Plan: Multi-Agent Architecture

> **⚠️ SUPERSEDED — not the current architecture.** This plan's `delegate_to_agent`/
> `MultiAgentOrchestrator` design (keyword-routed sub-agents invoked via `asyncio.gather()`)
> was replaced before being built out this way. The request-time agent is now
> `StrandsOrchestrator` — a single Strands `Agent` per request (`specs/plan-strands-migration.md`).
> Separately, a background multi-agent system does exist, but with a different design entirely
> (a shared entity/claim knowledge graph reconciled via peer-agent negotiation, not query-time
> sub-agent delegation) — see `specs/plan-multi-agent-knowledge.md`. Kept here only as a historical
> record of the design considered at the time.

**Goal**: Redesign AgentOrchestrator from a single agent with 6 tools into a coordinated
team of specialized agents, each with domain expertise, sharing DB and user context.

**Date**: 2026-09-02
**Status**: Design — pending review before implementation

---

## Context & Prior Decisions

This plan builds on top of the already-implemented "Agent Memory & Learning Upgrade"
(`specs/plan-agent-memory-upgrade.md`, status: Implemented). The foundation is solid:
- `generate_with_tools()` works in `LLMClient`
- `ConversationTurn` persists session history
- `Memory` (learnings) with pgvector dedup
- `save_learning` / `search_learnings` tools functional
- `MemoryRetrieverTool` supports `source=` filter already (key reuse below)

Prior decision from `plan-intelligent-learning.md`: do NOT add new DB columns or new
top-level tools. That constraint guided some design choices here (see Trade-offs section).

---

## Architecture Diagram

```
                        CLI / HTTP Client
                              │
                    POST /agent/query
                    {question, session_id}
                              │
                              ▼
                 ┌────────────────────────┐
                 │   OrchestratorAgent    │
                 │  (AgentOrchestrator)   │
                 │                        │
                 │  Tools exposed:        │
                 │  • delegate_to_agent   │◄── new: sub-agents as tools
                 │  • search_learnings    │
                 │  • save_learning       │
                 │  • get_user_style      │
                 └────────────┬───────────┘
                              │
           asyncio.gather() when independent
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                      │
        ▼                     ▼                      ▼
 ┌─────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ Domain      │   │ CrossKnowledge   │   │  Tasks           │
 │ Agents      │   │ Agent            │   │  Agent           │
 │             │   │                  │   │                  │
 │ Slack Agent │   │ Tools:           │   │ Tools:           │
 │ Outlook     │   │ • search_memory  │   │ • list_tasks     │
 │ Agent       │   │   (all sources)  │   │ • save_learning  │
 │ Fathom      │   │ • search_learni- │   │ • search_learni- │
 │ Agent       │   │   ngs            │   │   ngs            │
 │ Notion      │   │ • save_learning  │   │ • get_calendar   │
 │ Agent       │   │ • get_calendar   │   │                  │
 │             │   │                  │   │ Behavior:        │
 │ Tools each: │   │ Behavior:        │   │ - Lists tasks    │
 │ • search_me-│   │ - Correlates     │   │ - Asks user if   │
 │   mory      │   │   across sources │   │   each pending   │
 │   (source=X)│   │ - Owner=Mariano  │   │   is still active│
 │             │   │   → deep dive    │   │ - Saves confirm- │
 └─────────────┘   │   all sources    │   │   ation as       │
                   └──────────────────┘   │   learning       │
                                          └──────────────────┘

Legend:
  OrchestratorAgent = the only LLM call that talks back to the user
  Sub-agents = LLM calls that return structured text to the orchestrator
  All agents share the same db: AsyncSession and user_id: UUID
```

---

## Design Decision 1: Communication Pattern

**Decision**: Sub-agents are implemented as async Python functions (not LLM tools exposed
to the orchestrator via Anthropic's tool-use API). They are invoked directly by a Python
router layer inside `AgentOrchestrator`, then their results are injected into the
orchestrator's context before it makes its final LLM call.

**Rejected alternative — Sub-agents as tools of the orchestrator:**
Making `delegate_to_slack_agent`, `delegate_to_tasks_agent`, etc. actual Anthropic tools
would require the orchestrator to make N sequential tool-use iterations (one per sub-agent
call). This burns tokens and latency with no benefit. The orchestrator cannot run
`asyncio.gather()` because Anthropic's tool-use loop is sequential by nature — you get
back one assistant turn, dispatch tools, get results, call again. The parallelism advantage
is lost.

**Chosen pattern — Orchestrator-as-synthesizer:**
```
1. OrchestratorAgent receives question + session history
2. Routing layer (Python) decides which sub-agents are relevant for this query
3. Relevant sub-agents run concurrently via asyncio.gather()
4. Results are assembled into a structured context block
5. OrchestratorAgent makes ONE LLM call with: question + history + sub-agent results
6. Orchestrator synthesizes and responds to user
```

This means the orchestrator LLM sees sub-agent results as part of the user message context,
not as tool outputs. Sub-agents still run their own internal `generate_with_tools()` loops.

**Implication**: The orchestrator does NOT use Anthropic tool-use for delegation. It uses
tool-use only for `search_learnings`, `save_learning`, and `get_user_style` — things it
needs to do itself before or after synthesis.

---

## Design Decision 2: Sub-agent Invocation (Routing)

The orchestrator determines which sub-agents to invoke via **keyword routing + LLM intent
classification**. For MVP we use keyword routing (fast, free, deterministic):

```python
# Routing rules (in order of priority)
ROUTING_RULES = {
    "tasks_agent": ["pendiente", "tarea", "compromiso", "vence", "deadline",
                    "pending", "commitment", "task", "overdue", "ownership"],
    "cross_knowledge_agent": ["quién", "who", "dueño", "owner", "de quién",
                              "correlacion", "entre plataformas", "contexto de"],
    "domain_slack":   ["slack", "canal", "mensaje", "thread", "dm"],
    "domain_outlook": ["email", "correo", "outlook", "inbox", "calendario",
                       "calendar", "reunión", "meeting", "calendar"],
    "domain_fathom":  ["reunión", "meeting", "transcripción", "transcript",
                       "fathom", "call", "llamada", "notas"],
    "domain_notion":  ["notion", "página", "page", "documento", "database"],
    "domain_teams":   ["teams", "chat", "microsoft"],
}
```

Default behavior: if no specific routing match, invoke `cross_knowledge_agent` only
(always-on general agent).

The routing logic lives in `AgentOrchestrator._route_query()` and returns a
`List[str]` of agent keys to invoke.

---

## Design Decision 3: Tool Assignment per Agent

Each agent has a focused tool set. All agents share the same `LLMClient` instance.

| Agent | Tools | LLM call |
|---|---|---|
| `OrchestratorAgent` | `get_user_style`, `search_learnings`, `save_learning` | Yes — final synthesis |
| `SlackAgent` | `search_memory(source="slack")` | Yes — internal tool-use loop |
| `OutlookAgent` | `search_memory(source="outlook")`, `get_calendar` | Yes |
| `TeamsAgent` | `search_memory(source="teams")` | Yes |
| `FathomAgent` | `search_memory(source="fathom")` | Yes |
| `NotionAgent` | `search_memory(source="notion")` | Yes |
| `CrossKnowledgeAgent` | `search_memory` (all sources), `search_learnings`, `save_learning` | Yes |
| `TasksAgent` | `list_tasks`, `save_learning`, `search_learnings`, `get_calendar` | Yes |

Domain agents only call `search_memory` with their specific `source=` filter. This is not
a new capability — `MemoryRetrieverTool` already supports `source=` filtering.

---

## Design Decision 4: Confirmation Flow for Tasks

**Problem**: When TasksAgent asks "is commitment X still active?" the user's answer arrives
on the NEXT chat turn, not within the same tool-use loop.

**Solution — Learning as state:**
The TasksAgent does NOT wait for user confirmation within a single query. Instead:

1. When listing tasks with unknown/uncertain ownership or stale status, TasksAgent
   includes explicit confirmation requests in its output text.
2. The OrchestratorAgent surfaces those questions to the user.
3. On the NEXT turn, the OrchestratorAgent sees:
   - Conversation history (from `ConversationTurn`) includes the previous question
   - User's response is the current `question` parameter
4. OrchestratorAgent routes to `TasksAgent` again (or `CrossKnowledgeAgent`) which:
   - Reads history context and interprets the confirmation
   - Calls `save_learning` with: "User confirmed that commitment [X] is still active as of [date]"
   - OR: "User confirmed that commitment [X] is no longer active / was resolved"

**Why this works**: The `ConversationTurn` history is already loaded into every query.
The agent can read prior context and understand that the user is responding to a confirmation
request. No new DB state needed.

**What we do NOT build**: A separate "pending confirmation" state machine or session flag.
The conversation history IS the state machine.

---

## Design Decision 5: API Surface

**The `/agent/query` endpoint does not change.** The `AgentQueryRequest` and
`AgentQueryResponse` schemas remain identical. The multi-agent behavior is fully internal.

The CLI (`cli/chat.py`, `cli/api_client.py`) requires zero changes.

**Rationale**: The orchestrator is the single point of contact. The fact that it now
internally spawns sub-agents is an implementation detail. Adding `agents_invoked: List[str]`
to the response would be useful for debugging but is deferred to a later phase.

---

## Design Decision 6: Session History Ownership

**Only OrchestratorAgent persists ConversationTurn rows.** Sub-agents do not write to
`conversation_turns`. Sub-agent outputs are ephemeral — they exist only within the
orchestrator's LLM context for that single query.

This keeps the session history clean: the user sees a coherent conversation between them
and the orchestrator, not internal agent-to-agent communication.

---

## Design Decision 7: System Prompts Per Agent

Each agent has a focused system prompt. Domain agents are intentionally narrow.

```
OrchestratorAgent system prompt:
  "You are an AI Chief of Staff. Your team of specialists has already researched
   the user's question across all their platforms and memory. Your job is to
   synthesize their findings into a single, coherent, actionable response.
   You have also called get_user_style and search_learnings for long-term context.
   Never make up information not present in the specialist reports."

TasksAgent system prompt:
  "You are a commitments manager. Your job is to review the user's pending tasks
   and produce a clear, honest status report. NEVER assume a task is complete.
   NEVER assume ownership. If ownership is unclear, say so and ask the user directly.
   If a task looks stale (no activity in over 2 weeks), flag it and ask if it's
   still active. When the user confirms or denies a task's status, that confirmation
   should be saved as a learning."

CrossKnowledgeAgent system prompt:
  "You are a cross-platform knowledge analyst. Search broadly across all sources
   before answering. When Mariano (the user) appears as owner of a task or
   commitment, proactively investigate the full context: what was said, where,
   by whom, and what the current status is. Save any new insight you discover
   as a learning. Never invent facts."

DomainAgent system prompt (template, one per source):
  "You are the {source} specialist. You have access only to content from {source}.
   Search thoroughly and report what you find. Do not speculate beyond your data."
```

---

## File Structure

### New Files

```
app/services/agent/
├── orchestrator.py          ← renamed/evolved from agent.py (main entry point)
├── router.py                ← keyword routing logic (_route_query)
├── agents/
│   ├── __init__.py
│   ├── base_agent.py        ← BaseSubAgent: shared LLM call wrapper
│   ├── domain_agent.py      ← SlackAgent, OutlookAgent, TeamsAgent, FathomAgent, NotionAgent
│   ├── cross_knowledge_agent.py  ← CrossKnowledgeAgent
│   └── tasks_agent.py       ← TasksAgent (confirmation flow)
├── agent.py                 ← kept as thin backward-compat shim (imports from orchestrator.py)
├── tool_definitions.py      ← no change (existing)
├── learning_extractor.py    ← no change (existing)
└── tools/                   ← no change (existing)
    ├── memory_retriever.py
    ├── task_manager.py
    ├── calendar_sync.py
    ├── style_analyzer.py
    ├── save_learning.py
    └── search_learnings.py
```

### Modified Files

| File | Change |
|---|---|
| `app/services/agent/agent.py` | Thin shim: `AgentOrchestrator` imports and delegates to `orchestrator.py` for backward compat |
| `app/api/routers/agent.py` | No change required (imports `AgentOrchestrator` from `agent.py` shim) |
| `app/api/schemas/briefing.py` | Optional: add `agents_invoked: List[str]` to response (Phase 3) |

### Not Changed

- `app/services/llm/claude_client.py` — `generate_with_tools()` is sufficient as-is
- `app/services/agent/tools/` — all existing tool implementations reused
- `app/models/` — no new DB tables or columns
- `cli/` — no changes
- `alembic/` — no new migrations

---

## Phase Plan

### Phase 1 — BaseSubAgent + Domain Agents

**Goal**: Extract the 5 domain-scoped agents from the current orchestrator. Each domain
agent can search its own source and return structured text.

- [ ] Create `app/services/agent/agents/__init__.py`
- [ ] Create `app/services/agent/agents/base_agent.py`
  - `BaseSubAgent(llm_client, embedder)` with `async def run(db, user_id, question) -> str`
  - Internal `generate_with_tools()` call with agent-specific tools and system prompt
  - Returns plain text summary (not raw tool outputs)
- [ ] Create `app/services/agent/agents/domain_agent.py`
  - `DomainAgent(source: str)` subclass of `BaseSubAgent`
  - Tools: `search_memory` filtered to `source=self.source`
  - Instantiate 5 agents: `SlackAgent`, `OutlookAgent`, `TeamsAgent`, `FathomAgent`, `NotionAgent`
- [ ] Create `app/services/agent/router.py`
  - `AgentRouter.route(question: str) -> List[str]` returns agent keys
  - Keyword matching + default fallback to `cross_knowledge`
- [ ] Estimated complexity: **medium**

### Phase 2 — CrossKnowledgeAgent + TasksAgent

**Goal**: Build the two high-value agents with their specialized behaviors.

- [ ] Create `app/services/agent/agents/cross_knowledge_agent.py`
  - `CrossKnowledgeAgent(llm_client, embedder)` subclass of `BaseSubAgent`
  - Tools: `search_memory` (no source filter), `search_learnings`, `save_learning`
  - System prompt instructs: if owner appears to be Mariano → search all sources for context
  - System prompt instructs: never assume ownership, flag ambiguity explicitly
- [ ] Create `app/services/agent/agents/tasks_agent.py`
  - `TasksAgent(llm_client, embedder)` subclass of `BaseSubAgent`
  - Tools: `list_tasks`, `save_learning`, `search_learnings`, `get_calendar`
  - System prompt: flag stale tasks, ask for confirmation, save confirmations as learnings
  - Returns structured report: confirmed active tasks, flagged-for-confirmation tasks, overdue tasks
- [ ] Estimated complexity: **medium-high** (system prompt engineering is the main effort)

### Phase 3 — OrchestratorAgent (synthesizer)

**Goal**: Replace the existing `AgentOrchestrator.query()` implementation with the new
routing + parallel execution + synthesis pattern.

- [ ] Create `app/services/agent/orchestrator.py`
  - `MultiAgentOrchestrator(llm_client, embedder)` class
  - `async def query(db, user_id, question, session_id) -> Dict`
  - Loads `ConversationTurn` history (same logic as today)
  - Calls `AgentRouter.route(question)` to select agents
  - Runs selected sub-agents via `asyncio.gather()`
  - Builds synthesis prompt: question + history + sub-agent reports
  - Calls `generate_with_tools()` with limited tool set: `get_user_style`, `search_learnings`, `save_learning`
  - Persists turns via existing `_persist_turns()` logic
- [ ] Update `app/services/agent/agent.py`
  - `AgentOrchestrator` becomes a thin shim that instantiates `MultiAgentOrchestrator`
  - `query()` delegates to `MultiAgentOrchestrator.query()`
  - All existing imports in `app/api/routers/agent.py` continue to work unchanged
- [ ] Estimated complexity: **high** (integration + prompt engineering + parallel execution)

### Phase 4 — Confirmation Loop for Tasks (iteration)

**Goal**: Tune the TasksAgent + OrchestratorAgent prompts so the confirmation flow works
reliably in multi-turn conversations.

- [ ] Add `source_type="user_confirmation"` to save_learning calls from TasksAgent
- [ ] Add integration test: simulate 2-turn conversation where user confirms a task
- [ ] Tune `TasksAgent` system prompt based on observed behavior
- [ ] Tune `OrchestratorAgent` synthesis prompt to surface confirmation questions clearly
- [ ] Estimated complexity: **medium** (mostly prompt tuning + testing)

### Phase 5 — Observability (optional, Phase 3 follow-up)

**Goal**: Surface which agents ran, for debugging.

- [ ] Add `agents_invoked: List[str]` to `AgentQueryResponse` schema
- [ ] Pass through from `MultiAgentOrchestrator.query()` return dict
- [ ] Log sub-agent execution times
- [ ] Estimated complexity: **low**

---

## Key Design Patterns

### BaseSubAgent.run() contract

```python
class BaseSubAgent:
    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        question: str,
        conversation_context: str,  # last N turns as plain text, for sub-agent awareness
    ) -> SubAgentResult:
        ...

@dataclass
class SubAgentResult:
    agent_name: str
    findings: str        # plain text summary for the orchestrator
    tool_calls: List[ToolCall]  # for logging/sources extraction
    error: Optional[str] = None
```

The orchestrator assembles results:
```python
context_block = "\n\n".join([
    f"## {r.agent_name} findings\n{r.findings}"
    for r in results
    if r.error is None
])
```

### asyncio.gather() pattern

```python
tasks = [agent.run(db, user_id, question, conv_ctx) for agent in selected_agents]
results: List[SubAgentResult] = await asyncio.gather(*tasks, return_exceptions=True)
# Filter out exceptions, log them, continue with partial results
```

### Synthesis prompt structure

```
[System: orchestrator system prompt]
[Conversation history: last N turns]
[User: current question]
[Injected context block: sub-agent findings]
```

The injected context is appended to the user message (not as a separate role), keeping
the Anthropic message format valid (alternating user/assistant only).

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Latency increase from multiple LLM calls | High | High | asyncio.gather() runs independent sub-agents in parallel; only routed agents run (not all 7 every time) |
| Token cost increase | High | Medium | Domain agents only run when routed; each has narrow tool set (fewer iterations); orchestrator has only 3 tools |
| Sub-agent returns hallucinated findings | Medium | High | System prompts explicitly say "never invent facts not in tool results"; orchestrator prompt says "only synthesize what specialists reported" |
| Confirmation loop breaks across sessions | Medium | Medium | `ConversationTurn` history is the state; 24h expiry means stale confirmations are not mixed across days |
| Routing misses relevant agent | Medium | Low | Default fallback to `cross_knowledge_agent`; routing is additive (can match multiple agents) |
| Anthropic API rate limits under parallel calls | Low | High | asyncio.gather() means ~7 concurrent calls possible; existing retry logic in `_call_anthropic_with_retry()` handles this; stagger with `asyncio.sleep(0.1)` between batches if needed |
| Backward compat break in agent.py | Low | High | Shim pattern ensures `AgentOrchestrator` class still importable from `agent.py` with identical interface |

---

## What Is NOT in This Plan (and Why)

| Excluded | Reason |
|---|---|
| New DB tables / columns | Prior decision from `plan-intelligent-learning.md`: ownership and confirmations live in `memories` table, not a new schema |
| New API endpoints | Multi-agent is internal; single `/agent/query` endpoint is sufficient |
| Agent-to-agent tool calls (Anthropic tool-use for delegation) | Rejected — kills parallelism, adds token overhead, no benefit over Python function calls |
| Persistent sub-agent conversation history | Sub-agents are stateless per query; only orchestrator persists turns. Sub-agents are specialists, not persistent entities |
| New Python packages | Constraint: no new dependencies |
| Agent specialization via fine-tuning | Not applicable; all agents use same `LLMClient` with different system prompts |
| UI / CLI changes | Multi-agent is invisible to the user; behavior improves, interface stays the same |
| `confidence_score` on Commitment model | Decided against in prior plan; ownership ambiguity handled via `memories` |

---

## Open Questions for Review

1. **Routing granularity**: Should we invoke ALL domain agents on ambiguous queries (default: all)
   or only `cross_knowledge_agent` (default: cross_knowledge only)? Running all 5 domain agents
   on every query is safe but expensive. Proposed default: only `cross_knowledge_agent` unless
   a specific source keyword is detected.

2. **Sub-agent max_iterations**: How many tool-use iterations per sub-agent? Proposed: 3
   (vs orchestrator's 10). Domain agents with 1 tool need at most 2 (search + done).

3. **Conversation context for sub-agents**: Should sub-agents receive the last N turns of
   conversation history? Proposed: yes, as plain text summary only (not as Anthropic messages),
   so sub-agents understand what was already asked/answered.

4. **TasksAgent confirmation phrasing**: The TasksAgent needs to phrase confirmation requests
   in a way the orchestrator will surface clearly. Should there be a structured output format
   (e.g., JSON with `confirmations_needed: [...]`) or is plain text sufficient? Plain text
   is simpler but harder to parse for the orchestrator.

5. **Cost budget**: Each full multi-agent query could trigger 3-5 LLM calls. At current
   usage levels is this acceptable? Recommended: add a `MULTI_AGENT_ENABLED=false` env var
   as an escape hatch, so the system can fall back to the current single-agent loop.

---

## Implementation Sequence (Recommended Order)

```
Phase 1A — BaseSubAgent + DomainAgent (+ unit tests)
Phase 1B — AgentRouter (+ unit tests for routing rules)
Phase 2A — CrossKnowledgeAgent (+ unit tests)
Phase 2B — TasksAgent (+ unit tests for confirmation text)
Phase 3A — MultiAgentOrchestrator (orchestrator.py)
Phase 3B — agent.py shim update
Phase 3C — Integration test: full 2-turn query through the new stack
Phase 4  — Confirmation loop tuning (integration test with mocked LLM)
Phase 5  — Observability (agents_invoked in response)
```

---

## Files to Create

| File | Purpose |
|---|---|
| `app/services/agent/orchestrator.py` | `MultiAgentOrchestrator` — new main entry point |
| `app/services/agent/router.py` | `AgentRouter` — keyword-based routing |
| `app/services/agent/agents/__init__.py` | Package init, `SubAgentResult` dataclass |
| `app/services/agent/agents/base_agent.py` | `BaseSubAgent` abstract class |
| `app/services/agent/agents/domain_agent.py` | 5 domain agents (Slack, Outlook, Teams, Fathom, Notion) |
| `app/services/agent/agents/cross_knowledge_agent.py` | `CrossKnowledgeAgent` |
| `app/services/agent/agents/tasks_agent.py` | `TasksAgent` with confirmation flow |
| `tests/unit/test_agent_router.py` | Routing rule unit tests |
| `tests/unit/test_domain_agents.py` | Domain agent tool-set and prompt tests |
| `tests/unit/test_tasks_agent.py` | TasksAgent confirmation phrasing tests |
| `tests/integration/test_multi_agent_query.py` | End-to-end 2-turn confirmation test |

## Files to Modify

| File | Change |
|---|---|
| `app/services/agent/agent.py` | Thin shim — `AgentOrchestrator.query()` delegates to `MultiAgentOrchestrator` |
| `app/api/schemas/briefing.py` | (Phase 5 only) Add `agents_invoked: List[str] = []` |
