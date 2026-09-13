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

### 11. `agent_runs` (Backoffice — One Row Per Agent/Swarm Invocation)
Part of the knowledge-system backoffice (`specs/plan-knowledge-backoffice.md`). Domain agents,
reconciliation, and peer negotiations previously discarded their conversation once they returned
a summary string — this is where it's persisted instead.
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `agent_key`: Text (e.g. 'slack', 'rd', 'reconciliation', 'orchestrator')
- `run_type`: Enum ('domain_agent', 'rd_agent', 'reconciliation', 'negotiation', 'chat')
- `trigger`: Enum ('scheduler', 'manual', 'api')
- `status`: Enum ('running', 'completed', 'failed'), `model_id`: Text (nullable)
- `started_at`, `finished_at`, `duration_ms`, `input_tokens`, `output_tokens`, `total_tokens`
- `summary`: Text (nullable), `error`: Text (nullable), `stats`: JSONB
- `parent_run_id`: UUID (FK -> agent_runs.id, SET NULL) — a negotiation triggered by another run
  (`ask_peer_agents`, `negotiate_same_as`, the chat agent's `ask_domain_agents`) nests under it

### 12. `agent_run_events` (Backoffice — Ordered Conversation Steps)
- `id`: UUID (PK), `run_id`: UUID (FK -> agent_runs.id), `seq`: Integer (ordering)
- `event_type`: Enum ('assistant_text', 'tool_call', 'tool_result', 'handoff', 'verdict', 'error')
- `actor`: Text (nullable), `tool_name`: Text (nullable), `payload`: JSONB
- `created_at`: Timestamp — immutable once written, no `updated_at`

### 13. `agent_configs` (Backoffice — Per-Agent Overrides)
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `agent_key`: Text, `enabled`: Boolean (default true)
- `model_id`: Text (nullable), `system_prompt`: Text (nullable) — `NULL` means "use the code
  default"; a user with no row at all gets exactly the hardcoded behavior
- `enabled_tools`: JSONB list (nullable), `mcp_server_ids`: JSONB list (default `[]`)
- `params`: JSONB (default `{}`)
- Unique on `(user_id, agent_key)`

### 14. `mcp_servers` (Backoffice — User-Registered MCP Servers)
- `id`: UUID (PK), `user_id`: UUID (FK -> users.id)
- `name`: Text, `url`: Text, `auth_header`: Text (default 'Authorization')
- `api_key_encrypted`: Text (nullable) — Fernet-encrypted, same pattern as
  `integrations.access_token`
- `enabled`: Boolean (default true)
- `allowed_tools` / `rejected_tools`: JSONB lists (nullable) — map to Strands'
  `MCPClient(tool_filters=...)`
- `last_checked_at`: Timestamp (nullable), `last_status`: Text (nullable)
- `discovered_tools`: JSONB list (default `[]`)

---

## 🔍 Key Queries

### Semantic Search
`SELECT content FROM documents WHERE user_id = X AND embedding <=> [query_vector] < 0.5 ORDER BY embedding <=> [query_vector] LIMIT 5;`

### Pending Promises for Daily Briefing
`SELECT commitment_text, due_date FROM commitments WHERE user_id = X AND status = 'pending' AND due_date <= NOW() + INTERVAL '1 day';`
