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

## Key Relationships
- User -> Identities (1:N, cascade delete)
- User -> Integrations (1:N, cascade delete)
- User -> Documents (1:N, cascade delete)
- User -> Commitments (1:N, cascade delete)
- Document -> Commitments (1:N, cascade delete)
- User -> Entities -> EntityClaims / EntityLinks / PendingQuestions (1:N, cascade delete)
- Document -> ProcessedDocument (1:1 per source, cascade delete) — I+D platform data has no
  Document row; it's read live from its MCP server instead

## Data Flow
- **Write**: Connector fetch -> Clean -> Chunk -> Embed (OpenAI batch) -> Upsert to `documents` -> Commitment detection (Claude) -> Store to `commitments`
- **Read**: User query -> Embed query -> pgvector cosine search + metadata filters -> Top-K chunks -> Claude RAG -> Response
- **Dedup**: `(user_id, source, source_id)` unique index prevents duplicates on re-sync
