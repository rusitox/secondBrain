# Technical Architecture: AI Chief of Staff

## Technology Stack

- **Language:** Python 3.8+
- **Framework:** FastAPI (async)
- **ORM:** SQLAlchemy 2.0 (async, mapped_column style)
- **Database:** PostgreSQL 16+ with pgvector (Supabase-compatible)
- **Embeddings:** OpenAI (`text-embedding-3-small`, 1536 dims)
- **LLM:** Claude (Anthropic API) for reasoning, commitment detection, briefings, digests
- **Agent:** Custom multi-agent orchestrator (Anthropic tool-use API, asyncio.gather parallelism)
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

Multi-agent orchestrator (`MultiAgentOrchestrator`) with parallel domain specialists:

| Sub-agent | Tools | Responsibility |
|---|---|---|
| `SlackAgent` | search_memory(slack) | Slack channels and DMs |
| `OutlookAgent` | search_memory(outlook), get_calendar | Emails + calendar |
| `TeamsAgent` | search_memory(teams) | Microsoft Teams chats |
| `FathomAgent` | search_memory(fathom) | Meeting transcripts (with speaker attribution) |
| `NotionAgent` | search_memory(notion) | Pages and database items |
| `CrossKnowledgeAgent` | search_memory(all), search_learnings, save_learning | Cross-platform patterns and long-term memory |
| `TasksAgent` | list_tasks, get_calendar, search_learnings, save_learning | Pending commitments with ownership verification |

**Query pipeline:**
1. Keyword routing selects relevant domain agents (always includes CrossKnowledge + Tasks)
2. Sub-agents run concurrently via `asyncio.gather()`, each with an isolated DB session
3. Sub-agent outputs are synthesized into a single response via a final LLM call
4. Conversation history persisted to `conversation_turns` table for multi-turn sessions
5. Long-term memory (cross-session insights) stored in `memories` table via `save_learning`

**Ownership policy:** TasksAgent never assumes task ownership — always asks for explicit user confirmation; confirmations saved as high-importance learnings.

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
    ↓
Commitment Detection (Claude) → Commitments table ←→ Notion Sync
    ↓
CLI Chat ←→ REST API ←→ MultiAgentOrchestrator
                            ↓ asyncio.gather()
                Slack / Outlook / Teams / Fathom / Notion / CrossKnowledge / Tasks agents
                            ↓ synthesis
                        Final answer (Claude)
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

5 core models with UUID primary keys and timestamps:

| Model | Key Fields | Notes |
|---|---|---|
| User | email, full_name, timezone | Identity owner |
| Identity | persona_description, tone_guidelines, heuristics | JSON heuristics field |
| Integration | platform (enum), encrypted access/refresh tokens | Fernet-encrypted tokens |
| Document | content, embedding (vector 1536), source, source_id | pgvector for semantic search |
| Commitment | commitment_text, owner, due_date, priority, status, notion_page_id | Bidirectional Notion sync |
