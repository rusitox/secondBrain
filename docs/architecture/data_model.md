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

## Key Relationships
- User -> Identities (1:N, cascade delete)
- User -> Integrations (1:N, cascade delete)
- User -> Documents (1:N, cascade delete)
- User -> Commitments (1:N, cascade delete)
- Document -> Commitments (1:N, cascade delete)

## Data Flow
- **Write**: Connector fetch -> Clean -> Chunk -> Embed (OpenAI batch) -> Upsert to `documents` -> Commitment detection (Claude) -> Store to `commitments`
- **Read**: User query -> Embed query -> pgvector cosine search + metadata filters -> Top-K chunks -> Claude RAG -> Response
- **Dedup**: `(user_id, source, source_id)` unique index prevents duplicates on re-sync
