# Memory Logic: The RAG Cycle

## 1. The Ingestion Loop (Data In)
Connector fetch -> Source-specific cleaning (email signatures, Slack mentions, Teams system events, Fathom VTT headers) -> Chunking (RecursiveCharacterTextSplitter, 800 chars, 100 overlap) -> Batch embedding (OpenAI) -> Upsert to `documents` table (dedup by `user_id, source, source_id`).

## 2. The Commitment Detection Loop (Proactive Extraction)
After ingestion, cleaned text is analyzed by Claude with few-shot prompts to detect promises and action items. Extracted commitments are stored in the `commitments` table with owner, due date, priority, and link to source document. Supports both English and Spanish.

## 3. The Retrieval Loop (The Reader)
User query -> Embed query (OpenAI) -> pgvector cosine similarity search with HNSW index -> Metadata filtering (date range, source, author via JSONB) -> Top-K relevant chunks -> Context string.

## 4. The Generation Loop (The Brain)
Context string + User query + User identity (persona, tone, heuristics) -> Claude -> Grounded response with source traceability. Anti-hallucination: system prompt instructs Claude to answer only based on retrieved context.

## 5. The Agent Loop (Orchestration)
`StrandsOrchestrator` builds a single stateless AWS Strands `Agent` per request and runs Strands'
native multi-turn tool-use loop — no manual loop, no sub-agent fan-out. Core tools:
- **Memory Retriever**: Searches vector DB for relevant context
- **Task Manager**: Reads/writes to commitments table
- **Calendar Sync**: Checks upcoming meetings
- **Style Analyzer**: Retrieves user's identity for tone/style matching
- **Web Search / HTTP Request**: opt-in, only registered when configured (Brave API key /
  allowed domains)
- **Knowledge-graph tools**: `query_knowledge`, `get_pending_questions`, `confirm_pending_answer`
  — the orchestrator's read/write connection into the knowledge graph built by domain agents
  (see loop 7 below)

The agent decides which tools to invoke based on the query, enabling complex multi-step reasoning.

## 6. The Briefing Loop (Daily Proactive)
Scheduler triggers daily at user's configured time:
1. Fetch today's calendar events
2. Query pending/overdue commitments
3. Cross-reference participants with open commitments (contextual alerts)
4. Generate structured briefing via Claude

## 7. The Knowledge Graph Loop (Background, Multi-Agent)
Independent of the request/response agent loop above — see `specs/plan-multi-agent-knowledge.md`.
Driven by `KnowledgeAgentScheduler` (opt-in, `enable_knowledge_agents`): one periodic cycle per
user with an active integration, at `knowledge_agent_interval_minutes` (default 60m). Since the
"already processed" tracking table starts empty, the first cycle for any user finds their entire
pre-existing document history as unprocessed — backfill and ongoing processing are the same
mechanism, just spread across cycles rather than done in one burst. Each cycle:
One Strands domain agent per data source (Slack/Outlook/Teams/Fathom/Notion from the `documents`
table, plus an I+D-platform agent reading live from its own MCP server) runs a batch pass:
1. Read unprocessed source data (`get_unprocessed_documents`, or live MCP tools for I+D).
2. Identify entities (people, projects, initiatives, topics) and find-or-create them in the
   shared graph (case-insensitive name/alias match, or embedding similarity for cross-source
   candidates).
3. Record claims with real confidence, never overwriting a prior claim — a contradiction becomes
   a second, `disputed` claim.
4. **Resolution ladder** for anything unclear — never asks the human cold:
   `consult_knowledge_base` → `ask_peer_agents` (a scoped Strands `Swarm` negotiation with only
   the peer sources that already hold a claim about the entity) → `escalate_or_validate` (raises
   a `pending_question` for the human, carrying a candidate answer/confidence if steps 1-2
   produced one).
5. A separate reconciliation pass periodically finds cross-source duplicate entities (embedding
   similarity, or a deterministic email match) and merges them via a `same_as` `entity_link`,
   negotiating disagreements the same way (peer `Swarm`) before falling back to the human.
6. `GET /knowledge/status` exposes aggregate solidity metrics (entities by confidence bucket,
   claims by source, open pending questions, recent merges) so "the knowledge base gets more
   solid over time" is a verifiable claim, not an aspiration.
