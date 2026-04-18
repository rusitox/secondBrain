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

---

## 🔍 Key Queries

### Semantic Search
`SELECT content FROM documents WHERE user_id = X AND embedding <=> [query_vector] < 0.5 ORDER BY embedding <=> [query_vector] LIMIT 5;`

### Pending Promises for Daily Briefing
`SELECT commitment_text, due_date FROM commitments WHERE user_id = X AND status = 'pending' AND due_date <= NOW() + INTERVAL '1 day';`
