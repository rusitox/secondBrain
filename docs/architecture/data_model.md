# Data Model: Digital Twin Core

## Relational Schema (PostgreSQL + pgvector via Supabase)

### `users`
- `id`: UUID (PK)
- `email`: String(255), unique
- `full_name`: String(255)
- `timezone`: String(50), default "UTC"
- `created_at`, `updated_at`: Timestamp with timezone

### `identities` (The Twin's Persona)
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users, CASCADE)
- `persona_description`: Text
- `tone_guidelines`: Text
- `heuristics`: JSONB (decision-making patterns)
- `created_at`, `updated_at`: Timestamp with timezone

### `integrations`
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users, CASCADE)
- `platform`: Enum ('slack', 'outlook', 'teams', 'fathom')
- `access_token`: Text (encrypted via Fernet)
- `refresh_token`: Text (encrypted via Fernet)
- `last_sync_at`: Timestamp with timezone, nullable
- `is_active`: Boolean, default true
- `created_at`, `updated_at`: Timestamp with timezone

### `documents` (Semantic Memory / Vector Store)
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users, CASCADE)
- `content`: Text (the text chunk)
- `embedding`: Vector(1536) (OpenAI `text-embedding-3-small`)
- `source`: String(20) — platform identifier
- `source_id`: String(255) — original ID in external platform
- `metadata`: JSONB (author, timestamp, subject, channel, etc.)
- `created_at`, `updated_at`: Timestamp with timezone
- **Indexes**: HNSW on `embedding` (cosine ops), unique on `(user_id, source, source_id)`

### `commitments` (Promise Tracker)
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users, CASCADE)
- `document_id`: UUID (FK -> documents, SET NULL), nullable
- `commitment_text`: Text
- `owner`: Text, default "unknown"
- `due_date`: Timestamp with timezone, nullable
- `status`: Enum ('pending', 'completed', 'cancelled')
- `priority`: Integer, default 3
- `created_at`, `updated_at`: Timestamp with timezone

## Knowledge Graph (Multi-Agent Knowledge System)

Separate from the RAG `documents` table above — see `specs/plan-multi-agent-knowledge.md`.
Domain agents (one per data source, plus one for the I+D platform via its own MCP server)
propose structured entities and claims into a shared, cross-source graph, reconciled over time.

### `entities`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `entity_type`: Enum (person, project, initiative, topic, organization)
- `canonical_name`: Text, `aliases`: JSONB (list), `attributes`: JSONB (free-form facts)
- `embedding`: Vector(1536), nullable — used for cross-source duplicate detection
- `confidence`: Float, default 0.5 — the entity's "solidity" score, recomputed during reconciliation

### `entity_claims`
- `id`: UUID (PK), `entity_id`: UUID (FK -> entities, CASCADE), `user_id`: UUID (FK -> users, CASCADE)
- `source`: Text (e.g. `slack`, `outlook`, `rd`), `source_ref`: Text, nullable
- `claim_text`: Text, `claim_type`: Text, nullable, `confidence`: Float, default 0.5
- `status`: Enum (active, superseded, disputed, confirmed_by_user)
- `asserted_by_agent`: Text — claims are never overwritten in place; a contradiction becomes a
  second claim with `status=disputed`, never a silent replacement

### `entity_links`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `entity_id_a`, `entity_id_b`: UUID (FK -> entities, CASCADE)
- `relation_type`: Text (free-text; `same_as` is the reconciliation engine's merge relation)
- `confidence`: Float, default 0.5, `resolved_by`: Enum (deterministic, swarm, user)

### `pending_questions`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `raised_by_agent`: Text, `question_text`: Text, `context`: JSONB
- `target`: Enum (peer_agents, human) — a doubt always starts at `peer_agents`; only flips to
  `human` once nothing upstream resolves it
- `candidate_answer`: Text, nullable, `candidate_confidence`: Float, nullable — the best guess so
  far, carried forward so the human validates instead of answering cold
- `status`: Enum (open, answered, dismissed), `resolved_by`: Enum (knowledge_base, peer_swarm, human)
- `answer_text`: Text, nullable, `answered_at`: Timestamp with timezone, nullable

### `knowledge_processed_documents`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `document_id`: UUID (FK -> documents, CASCADE), unique
- `source`: Text — tracks which Document rows a domain agent already extracted, so a batch run
  never re-reads the same document twice

## Backoffice (Knowledge System Observability & Config)

Separate from the knowledge graph above — see `specs/plan-knowledge-backoffice.md`. Persists what
every domain agent / reconciliation pass / peer negotiation / chat run actually did (previously
discarded once a run returned its summary string), and lets model/prompt/tools/MCP servers be
overridden per agent without a code change.

### `agent_runs`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `agent_key`: Text (e.g. `slack`, `outlook`, `rd`, `reconciliation`, `orchestrator` — free text,
  not an enum, so a new agent doesn't need a migration)
- `run_type`: Enum (domain_agent, rd_agent, reconciliation, negotiation, chat)
- `trigger`: Enum (scheduler, manual, api)
- `status`: Enum (running, completed, failed), `model_id`: Text, nullable
- `started_at`, `finished_at`, `duration_ms`, `input_tokens`, `output_tokens`, `total_tokens`
- `summary`: Text, nullable, `error`: Text, nullable, `stats`: JSONB
- `parent_run_id`: UUID (FK -> agent_runs, SET NULL) — a negotiation triggered by another run
  (`ask_peer_agents`, `negotiate_same_as`, the chat agent's `ask_domain_agents`) nests under it

### `agent_run_events`
- `id`: UUID (PK), `run_id`: UUID (FK -> agent_runs, CASCADE), `seq`: Integer (ordering)
- `event_type`: Enum (assistant_text, tool_call, tool_result, handoff, verdict, error)
- `actor`: Text, nullable, `tool_name`: Text, nullable, `payload`: JSONB
- `created_at`: Timestamp — immutable once written, no `updated_at`

### `agent_configs`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `agent_key`: Text, `enabled`: Boolean, default true
- `model_id`: Text, nullable, `system_prompt`: Text, nullable — `NULL` means "use the code
  default"; a user with no row at all gets exactly the hardcoded behavior
- `enabled_tools`: JSONB list, nullable, `mcp_server_ids`: JSONB list, default `[]`
- `params`: JSONB, default `{}`
- Unique on `(user_id, agent_key)`

### `mcp_servers`
- `id`: UUID (PK), `user_id`: UUID (FK -> users, CASCADE)
- `name`: Text, `url`: Text, `auth_header`: Text, default `Authorization`
- `api_key_encrypted`: Text, nullable — Fernet-encrypted, same pattern as
  `Integration.access_token`, never stored/returned as plaintext outside the service layer
- `enabled`: Boolean, default true
- `allowed_tools` / `rejected_tools`: JSONB lists, nullable — map directly to Strands'
  `MCPClient(tool_filters=...)`
- `last_checked_at`: Timestamp, nullable, `last_status`: Text, nullable
- `discovered_tools`: JSONB list, default `[]`

## Key Relationships
- User -> Identities (1:N, cascade delete)
- User -> Integrations (1:N, cascade delete)
- User -> Documents (1:N, cascade delete)
- User -> Commitments (1:N, cascade delete)
- Document -> Commitments (1:N, cascade delete)
- User -> Entities -> EntityClaims / EntityLinks / PendingQuestions (1:N, cascade delete)
- Document -> ProcessedDocument (1:1 per source, cascade delete) — I+D platform data has no
  Document row; it's read live from its MCP server instead
- User -> AgentRuns -> AgentRunEvents (1:N, cascade delete); AgentRun -> AgentRun (self-referential
  `parent_run_id`, SET NULL on delete)
- User -> AgentConfigs / McpServers (1:N, cascade delete)

## Data Flow
- **Write**: Connector fetch -> Clean -> Chunk -> Embed (OpenAI batch) -> Upsert to `documents` -> Commitment detection (Claude) -> Store to `commitments`
- **Read**: User query -> Embed query -> pgvector cosine search + metadata filters -> Top-K chunks -> Claude RAG -> Response
- **Dedup**: `(user_id, source, source_id)` unique index prevents duplicates on re-sync
