# secondBrain

A personal knowledge management system (AI Chief of Staff / Digital Twin) based on FastAPI and SQLAlchemy. Ingests data from multiple communication platforms, tracks commitments, generates daily briefings, and provides cross-platform RAG querying via a CLI interface.

## Stack

- **Language**: Python 3.8+
- **Framework**: FastAPI (async)
- **ORM**: SQLAlchemy 2.0 (async, mapped_column style)
- **Database**: PostgreSQL + pgvector (Supabase)
- **Embeddings**: OpenAI (`text-embedding-3-small`, 1536 dims)
- **LLM**: Claude (Anthropic API) for reasoning, commitment detection, briefings
- **CLI**: Rich + prompt_toolkit
- **Package Manager**: pip

## Commands

```bash
python -m uvicorn app.main:app --reload   # Start dev server
python -m cli                             # Start CLI chat interface
mypy .                                    # Type check
pytest tests/                             # Run all tests
pytest tests/unit/                        # Unit tests only
pytest tests/integration/                 # Integration tests only
pytest --cov=app --cov-report=term-missing  # Coverage report
```

## Architecture

### Backend (`app/`)
FastAPI backend with async SQLAlchemy, organized in layers:

- **`app/core/`** — Config (pydantic-settings), database engine/session, security (Fernet encryption), logging
- **`app/models/`** — SQLAlchemy models: User, Identity, Integration, Document (with pgvector), Commitment
- **`app/api/routers/`** — REST endpoints: health, users, commitments, integrations, ingestion, query, agent, briefing, identity
- **`app/api/schemas/`** — Pydantic request/response models
- **`app/services/`** — Business logic:
  - `connectors/` — Platform connectors: MSGraph (Outlook email+calendar), Teams (chat), Slack, Fathom
  - `ingestion/` — Pipeline: cleaner → chunker → embedder → upsert
  - `retrieval/` — Semantic search with metadata filters
  - `llm/` — Claude client + prompt templates
  - `commitments/` — AI-powered commitment detection
  - `agent/` — LangChain agent with tools (memory retriever, task manager, style analyzer, calendar sync)
  - `briefing/` — Daily briefing generator + scheduler

### CLI (`cli/`)
Terminal-based chat interface consuming the REST API:

- **`cli/main.py`** — Entry point, event loop
- **`cli/onboarding.py`** — 5-step resumable onboarding wizard
- **`cli/chat.py`** — Main chat loop with agent queries
- **`cli/commands.py`** — Slash command router (`/briefing`, `/sync`, `/commitments`, etc.)
- **`cli/background.py`** — Periodic background sync
- **`cli/alerts.py`** — Proactive commitment alerts
- **`cli/api_client.py`** — Async httpx wrapper for all API calls
- **`cli/config.py`** — Local config persistence (`~/.secondbrain/config.json`)
- **`cli/display.py`** — Rich console formatting

### Connectors
| Connector | Class | Source | Data |
|---|---|---|---|
| Outlook | `MSGraphConnector` | `outlook` | Emails + calendar events |
| Teams | `TeamsConnector` | `teams` | 1:1 and group chat messages |
| Slack | `SlackConnector` | `slack` | Channel and DM messages |
| Fathom | `FathomConnector` | `fathom` | Meeting transcripts |

## Conventions

- Follow existing code patterns in the codebase
- All code must pass type checks before commit
- Use structured logging, never print() in production
- Write tests for new features
- Use Conventional Commits for commit messages
- Type hints for all function parameters and return types
- Async functions use async/await, not threading for I/O
- PEP 8 naming: snake_case functions/variables, PascalCase classes

## Key Files

- `app/main.py` — Entry point, router registration, lifespan
- `app/core/config.py` — Settings (pydantic-settings, .env)
- `app/core/database.py` — Async engine, session factory
- `app/models/` — SQLAlchemy models (Base, UUIDMixin, TimestampMixin)
- `app/api/routers/` — API endpoints (9 routers)
- `app/services/connectors/` — Platform connectors (4: outlook, teams, slack, fathom)
- `app/services/ingestion/pipeline.py` — Central data flow
- `app/services/retrieval/search.py` — Hybrid vector search
- `cli/` — CLI chat interface
- `requirements.txt` — Dependencies
- `specs/` — Product specs, implementation plans, QA plan
- `tests/` — Unit, integration, and E2E tests
