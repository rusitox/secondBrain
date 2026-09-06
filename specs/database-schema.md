# Database Schema: Digital Twin Core

This schema is designed for **Supabase (PostgreSQL + pgvector)**. It combines relational data for tracking and vector data for semantic memory.

## 🗄️ Tables

### 1. `users`
Stores basic user account information and global settings.
- `id`: UUID (PK)
- `email`: String (Unique)
- `full_name`: String
- `timezone`: String (Crucial for "Daily Briefing" timing)
- `created_at`: Timestamp

### 2. `identities` (The Twin's Persona)
Stores the "Digital Twin" configuration. This allows the agent to clone the user's style.
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users.id)
- `persona_description`: Text (The "who am I" prompt)
- `tone_guidelines`: Text (Rules: "Be concise", "Use professional Spanish", etc.)
- `heuristics`: JSONB (Decision-making patterns: "Always prioritize X over Y")
- `updated_at`: Timestamp

### 3. `integrations`
Stores credentials and sync state for external platforms.
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users.id)
- `platform`: Enum ('slack', 'outlook', 'teams', 'fathom')
- `access_token`: Encrypted String
- `refresh_token`: Encrypted String
- `last_sync_at`: Timestamp
- `is_active`: Boolean

### 4. `documents` (The Semantic Memory)
The core of the RAG system. Stores chunks of text and their embeddings.
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users.id)
- `content`: Text (The actual text chunk)
- `embedding`: Vector(1536) (OpenAI `text-embedding-3-small` size)
- `source`: Enum ('slack', 'outlook', 'teams', 'fathom')
- `source_id`: String (Original ID in the external platform)
- `metadata`: JSONB (Author, timestamp, project_id, thread_id)
- `created_at`: Timestamp

### 5. `commitments` (The Promise Tracker)
Relational table to track explicit promises extracted from interactions.
- `id`: UUID (PK)
- `user_id`: UUID (FK -> users.id)
- `document_id`: UUID (FK -> documents.id) - Link to the source text
- `commitment_text`: Text (e.g., "Send the budget report by Friday")
- `owner`: Text (who made the commitment, default "unknown")
- `due_date`: Timestamp (nullable)
- `status`: Enum ('pending', 'completed', 'cancelled')
- `priority`: Integer (1-5, default 3)
- `created_at`, `updated_at`: Timestamp with timezone

### 6. `entities` (Knowledge Graph Node)
Part of the multi-agent knowledge system (`specs/plan-multi-agent-knowledge.md`) — separate from
`documents`. Domain agents propose these; `confidence` is recalculated during reconciliation.
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `entity_type`: Enum ('person', 'project', 'initiative', 'topic', 'organization')
- `canonical_name`: Text, `aliases`: JSONB (list), `attributes`: JSONB (free-form facts)
- `embedding`: Vector(1536), nullable — cross-source duplicate detection
- `confidence`: Float (default 0.5) — the entity's "solidity" score

### 7. `entity_claims` (Provenance)
- `id`: UUID (PK), `entity_id`: UUID (FK -> entities.id), `user_id`: UUID (FK -> users.id)
- `source`: Text (e.g. 'slack', 'rd'), `source_ref`: Text (nullable)
- `claim_text`: Text, `claim_type`: Text (nullable), `confidence`: Float (default 0.5)
- `status`: Enum ('active', 'superseded', 'disputed', 'confirmed_by_user')
- `asserted_by_agent`: Text — a contradiction becomes a new `disputed` claim, never a silent overwrite

### 8. `entity_links` (Relationships & Merges)
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `entity_id_a`, `entity_id_b`: UUID (FK -> entities.id)
- `relation_type`: Text (free-text; 'same_as' = reconciliation merge), `confidence`: Float (default 0.5)
- `resolved_by`: Enum ('deterministic', 'swarm', 'user')

### 9. `pending_questions` (Resolution-Ladder State Machine)
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `raised_by_agent`: Text, `question_text`: Text, `context`: JSONB
- `target`: Enum ('peer_agents', 'human') — starts at peer_agents, flips to human only if unresolved
- `candidate_answer`: Text (nullable), `candidate_confidence`: Float (nullable)
- `status`: Enum ('open', 'answered', 'dismissed'), `resolved_by`: Enum ('knowledge_base', 'peer_swarm', 'human')
- `answer_text`: Text (nullable), `answered_at`: Timestamp (nullable)

### 10. `knowledge_processed_documents` (Watermark)
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `document_id`: UUID (FK -> documents.id), unique
- `source`: Text — tracks which documents a domain agent already extracted

---

## 🔍 Key Queries

### Semantic Search
`SELECT content FROM documents WHERE user_id = X AND embedding <=> [query_vector] < 0.5 ORDER BY embedding <=> [query_vector] LIMIT 5;`

### Pending Promises for Daily Briefing
`SELECT commitment_text, due_date FROM commitments WHERE user_id = X AND status = 'pending' AND due_date <= NOW() + INTERVAL '1 day';`
