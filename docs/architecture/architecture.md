# High-Level Architecture: Digital Twin Assistant

## Overview
The Digital Twin is a personalized AI assistant that acts as an AI Chief of Staff. It ingests professional interactions from multiple platforms, tracks commitments, generates daily briefings, and answers cross-platform queries grounded in the user's own data.

## Core Philosophy
- **Proactive Learning**: Automatically detect commitments and action items from ingested text.
- **Semantic Retrieval**: Vector embeddings (pgvector HNSW) for meaning-based search across all sources.
- **Augmented Intelligence**: LLM responses always grounded in retrieved user-specific context (RAG).
- **Privacy-First**: Tokens encrypted at rest (Fernet), row-level isolation by user_id.

## Component Stack
- **API**: FastAPI (async, 13 routers)
- **ORM**: SQLAlchemy 2.0 (async with asyncpg)
- **Memory Store**: PostgreSQL + pgvector (Supabase)
- **LLM**: Claude (Anthropic API) for reasoning, commitment detection, briefings; OpenAI models via Strands for the agent loop
- **Embeddings**: OpenAI `text-embedding-3-small` (1536 dims)
- **Orchestration**: `StrandsOrchestrator` — a single AWS Strands `Agent` per request running Strands' native multi-turn tool-use loop (memory retriever, task manager, calendar sync, style analyzer, web search, http request, plus knowledge-graph tools). No manual tool loop, no sub-agent fan-out.
- **Knowledge graph**: A separate multi-agent system (one Strands domain agent per data source, negotiating via scoped `Swarm`s) builds and reconciles a shared entity/claim graph in the background — see `specs/plan-multi-agent-knowledge.md`.
- **CLI**: Rich + prompt_toolkit (chat interface with onboarding wizard)

## Data Sources (Connectors)
| Connector | Platform | Data Type |
|---|---|---|
| MSGraphConnector | Outlook | Emails + calendar events |
| TeamsConnector | Teams | 1:1 and group chat messages |
| SlackConnector | Slack | Channel + DM messages |
| FathomConnector | Fathom | Meeting transcripts |
| NotionConnector | Notion | Pages + database items |

All connectors follow `BaseConnector` ABC: `fetch_items()`, `validate_token()`, with pagination and rate limit handling.

## Processing Pipeline
```
Sources -> Connector.fetch_items() -> Cleaner (source-specific) -> Chunker (800 chars, 100 overlap)
  -> Embedder (OpenAI batch) -> Upsert to documents table -> Commitment Detector (Claude) -> commitments table
```

## MVP Features
1. **Commitment Tracking** — Auto-detection of promises from ingested text, structured tracking with status/priority/due dates
2. **Daily Briefing** — Morning summary: agenda + pending commitments + contextual alerts (cross-referencing calendar participants with open commitments)
3. **Cross-Platform Querying** — RAG-powered natural language queries spanning all ingested sources

## Interface
CLI chat interface (`python -m cli`) with:
- 5-step resumable onboarding wizard
- Natural language queries routed to the Strands agent (`StrandsOrchestrator`)
- Slash commands (`/briefing`, `/sync`, `/commitments`, `/status`, etc.)
- Background periodic sync with proactive commitment alerts
