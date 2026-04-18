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
LangChain agent with Claude + 4 tools:
- **Memory Retriever**: Searches vector DB for relevant context
- **Task Manager**: Reads/writes to commitments table
- **Calendar Sync**: Checks upcoming meetings
- **Style Analyzer**: Retrieves user's identity for tone/style matching

The agent decides which tools to invoke based on the query, enabling complex multi-step reasoning.

## 6. The Briefing Loop (Daily Proactive)
Scheduler triggers daily at user's configured time:
1. Fetch today's calendar events
2. Query pending/overdue commitments
3. Cross-reference participants with open commitments (contextual alerts)
4. Generate structured briefing via Claude
