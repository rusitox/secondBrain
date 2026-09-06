# Technical Architecture: AI Chief of Staff

## Technology Stack

- **Language:** Python 3.8+
- **Framework:** FastAPI (async)
- **ORM:** SQLAlchemy 2.0 (async, mapped_column style)
- **Database:** PostgreSQL 16+ with pgvector (Supabase-compatible)
- **Embeddings:** OpenAI (`text-embedding-3-small`, 1536 dims)
- **LLM:** Claude (Anthropic API) for reasoning, commitment detection, briefings, digests
- **Agent:** AWS Strands Agents — `StrandsOrchestrator` builds one Strands `Agent` per request with all tools attached and runs Strands' native multi-turn tool-use loop
- **Knowledge graph:** A separate multi-agent system — one Strands domain agent per data source, negotiating via scoped `Swarm`s — builds and reconciles a shared entity/claim graph in the background
- **CLI:** Rich + prompt_toolkit
- **Security:** Fernet encryption for stored tokens

---

## System Architecture

### 1. Data Ingestion Pipeline

Modular connector architecture to ingest text from multiple sources:

**Connectors:**
| Connector | Class | Source | Data |
|---|---|---|---|
| Outlook | `MSGraphConnector` | `outlook` | Emails + calendar events (OAuth2 via MS Graph) |
| Teams | `TeamsConnector` | `teams` | 1:1 and group chat messages (MS Graph API) |
| Slack | `SlackConnector` | `slack` | Channel and DM messages (Bot Token) |
| Fathom | `FathomConnector` | `fathom` | Meeting transcripts |
| Notion | `NotionConnector` | `notion` | Pages + database items (Notion API v1) |

**Processing Flow:**
1. **Cleaning** — Remove noise (signatures, boilerplate)
2. **Chunking** — Split into semantic chunks (~500-1000 tokens)
3. **Embedding** — Convert chunks to vectors via OpenAI Embeddings
4. **Storage** — Upsert to `documents` table with metadata (source, timestamp, author)
5. **Commitment Detection** — Claude analyzes text for promises, deadlines, action items

### 2. Memory & Retrieval Layer

**Hybrid Search** strategy:
- **Semantic Search** — Vector search via pgvector for conceptually related information
- **Metadata Filtering** — Filter by date range, source, author, platform

### 3. The Agentic Core

`StrandsOrchestrator` (`app/services/agent/strands_orchestrator.py`) builds a single stateless
Strands `Agent` per request with every tool attached, and runs Strands' native multi-turn
tool-use loop directly — no manual loop, no keyword-routed sub-agent fan-out. Earlier iterations
of this project used a custom multi-agent orchestrator with domain-specific sub-agents invoked via
`asyncio.gather()`; that design was replaced by the Strands migration (`specs/plan-strands-migration.md`).

**Tools attached to the request-time agent** (`strands_tools.py`, wrapping implementations in `tools/`):
- `memory_retriever` — vector search across all ingested sources
- `task_manager` — reads/writes to `commitments`
- `calendar_sync` — checks upcoming meetings
- `style_analyzer` — retrieves the user's identity for tone/style matching
- `save_learning` / `search_learnings` — long-term cross-session memory (`memories` table)
- `web_search` / `http_request` — opt-in, only registered when configured
- `query_knowledge` / `get_pending_questions` / `confirm_pending_answer` — read/write access to
  the knowledge graph built by the domain agents below
- `SequentialToolExecutor` forces one tool call at a time within a turn, since every tool closes
  over the same `AsyncSession`

**Query pipeline:**
1. `StrandsOrchestrator` builds the Agent and hands it the question; Strands drives tool calls and
   multi-turn reasoning itself
2. Conversation history persisted to `conversation_turns` table for multi-turn sessions
3. Long-term memory (cross-session insights) stored in `memories` table via `save_learning`

### 3.1 The Multi-Agent Knowledge System (background, separate from the request-time agent)

A second, independent multi-agent system builds a shared entity/claim graph over time —
see `specs/plan-multi-agent-knowledge.md` for the full design. One Strands domain agent per
data source proposes entities and claims into the graph; agents resolve doubts among themselves
before ever asking the human:

| Component | Responsibility |
|---|---|
| `domain_agent.py` | Per-source (Slack/Outlook/Teams/Fathom/Notion) agent reading unprocessed `documents` |
| `rd_agent.py` | I+D platform agent — reads live from its own MCP server (no `documents` row), read-only (its one write tool is excluded) |
| `resolution.py` | `find_or_create_entity` (case-insensitive match), `consult_knowledge_base` |
| `swarm_negotiation.py` | Shared scoped-`Swarm` core used both proactively and by reconciliation |
| `reconciliation.py` | Cross-source duplicate detection (embedding similarity + deterministic email match), `same_as` merging, confidence recomputation |
| `store.py` | CRUD for entities/claims/links/pending_questions + `get_knowledge_stats` observability |
| `scheduler.py` | `KnowledgeAgentScheduler` — opt-in (`enable_knowledge_agents`) periodic per-user cycle: every Document-backed source, then the I+D agent if configured, then reconciliation. Not tied to `is_production` like the ingestion sync scheduler — every cycle makes real LLM calls |

**Resolution ladder** (never asks the human cold): `consult_knowledge_base` →
`ask_peer_agents` (a scoped `Swarm` with only the peer sources that already hold a claim about
the entity) → `escalate_or_validate` (raises a `pending_question` for the human, carrying a
candidate answer/confidence if the earlier steps produced one).

**Ownership policy:** claims are never overwritten in place — a contradiction becomes a second,
`disputed` claim, so both sides of a disagreement remain available to reconciliation.

### 4. Proactive Features

- **Daily Briefing** — Automated morning summary (agenda, pending commitments, alerts)
- **Weekly Digest** — Friday auto-publish to Notion (commitment stats, activity summary, next week plan)
- **Meeting Prep** — On-demand prep documents published to Notion
- **Commitment Alerts** — Proactive notifications for overdue or upcoming deadlines

### 5. Notion Integration

Bidirectional integration with Notion workspaces:
- **Read** — Ingest pages and database items as documents
- **Write** — Publish briefings, digests, and meeting prep as Notion pages
- **Sync** — Bidirectional commitment sync with last-write-wins conflict resolution
- **Workspace Setup** — Auto-creates Commitments, Briefings, and Meeting Prep databases

---

## Data Flow

```
Sources (Outlook/Teams/Slack/Fathom/Notion)
    ↓
FastAPI Ingestion Pipeline → Clean → Chunk → Embed → PostgreSQL+pgvector
    ↓                                                        ↓ (background, async)
Commitment Detection (Claude) → Commitments table ←→   Domain agents (Strands) per source
    ↓                                Notion Sync            ↓ resolution ladder / Swarm negotiation
CLI Chat ←→ REST API ←→ StrandsOrchestrator            Entities / Claims / Links / PendingQuestions
                            ↓ Strands tool-use loop          ↓
                query_knowledge / get_pending_questions ←────┘
                            ↓
                        Final answer
    ↓
Daily Briefing / Weekly Digest / Meeting Prep → Notion
```

---

## Security & Privacy

- **Token Encryption** — Integration tokens encrypted at rest with Fernet
- **OAuth2** — Standard authorization flows; no raw passwords stored
- **User Isolation** — All queries filtered by `user_id`
- **Config Permissions** — CLI config file restricted to owner (`0o600`)

---

## Database Schema

Core models, all with UUID primary keys and timestamps — see `specs/database-schema.md` for full
field lists including the knowledge-graph tables:

| Model | Key Fields | Notes |
|---|---|---|
| User | email, full_name, timezone | Identity owner |
| Identity | persona_description, tone_guidelines, heuristics | JSON heuristics field |
| Integration | platform (enum), encrypted access/refresh tokens | Fernet-encrypted tokens |
| Document | content, embedding (vector 1536), source, source_id | pgvector for semantic search |
| Commitment | commitment_text, owner, due_date, priority, status, notion_page_id | Bidirectional Notion sync |
| Entity | entity_type, canonical_name, aliases, attributes, embedding, confidence | Knowledge-graph node |
| EntityClaim | entity_id, source, claim_text, confidence, status | One source's assertion about an Entity, never overwritten in place |
| EntityLink | entity_id_a, entity_id_b, relation_type, resolved_by | `same_as` is the reconciliation merge relation |
| PendingQuestion | raised_by_agent, question_text, target, candidate_answer, status | The resolution-ladder state machine |
