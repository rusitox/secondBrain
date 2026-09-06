# secondBrain

A personal knowledge management system (AI Chief of Staff / Digital Twin) based on FastAPI and SQLAlchemy. Ingests data from multiple communication platforms, tracks commitments, generates daily briefings, and provides cross-platform RAG querying via a CLI interface.

## Stack

- **Language**: Python 3.8+
- **Framework**: FastAPI (async)
- **ORM**: SQLAlchemy 2.0 (async, mapped_column style)
- **Database**: PostgreSQL + pgvector (Supabase)
- **Embeddings**: OpenAI (`text-embedding-3-small`, 1536 dims)
- **LLM**: Claude (Anthropic API) for reasoning, commitment detection, briefings
- **Scheduler**: APScheduler (AsyncIOScheduler) for server-side periodic sync
- **Auth**: API key authentication (bcrypt hashed, `sb_` prefix)
- **CLI**: Rich + prompt_toolkit
- **Container**: Docker (multi-stage build), docker-compose
- **CI/CD**: GitHub Actions → GHCR
- **Package Manager**: pip (+ pyproject.toml for CLI-only install)

## Commands

```bash
python -m uvicorn app.main:app --reload   # Start dev server
python -m cli                             # Start CLI chat interface
python -m cli login                       # Login to remote server
python -m cli logout                      # Clear local credentials
python -m cli install                     # Run local installer
mypy app/ cli/ --ignore-missing-imports   # Type check
pytest tests/                             # Run all tests
pytest tests/unit/                        # Unit tests only
pytest tests/integration/                 # Integration tests only
pytest --cov=app --cov-report=term-missing  # Coverage report
docker compose up -d                      # Start local DB + server
./install.sh                              # Full local install
./install.sh --remote                     # CLI-only install + login
```

## Architecture

### Backend (`app/`)
FastAPI backend with async SQLAlchemy, organized in layers:

- **`app/core/`** — Config (pydantic-settings), database engine/session, security (Fernet encryption + API key auth), logging
- **`app/models/`** — SQLAlchemy models: User, Identity, Integration, Document (with pgvector), Commitment, APIKey, plus the knowledge-graph models (Entity, EntityClaim, EntityLink, PendingQuestion, ProcessedDocument)
- **`app/api/routers/`** — REST endpoints: health, users, commitments, integrations, ingestion, query, agent, briefing, identity, sync, auth, voice, knowledge
- **`app/api/schemas/`** — Pydantic request/response models
- **`app/services/`** — Business logic:
  - `connectors/` — Platform connectors: MSGraph (Outlook), Teams, Slack, Fathom, Notion
  - `ingestion/` — Pipeline: cleaner → chunker → embedder → upsert
  - `retrieval/` — Semantic search with metadata filters
  - `llm/` — Claude client + prompt templates
  - `commitments/` — AI-powered commitment detection
  - `agent/` — `StrandsOrchestrator` (AWS Strands Agents): builds a single stateless Strands `Agent` per request with all tools attached, runs Strands' native multi-turn tool-use loop, and returns the synthesized answer directly — no manual tool-use loop or sub-agent fan-out. Tools are `@tool`-decorated closures from `strands_tools.py` wrapping the implementations in `tools/`, plus knowledge-graph tools (`query_knowledge`, `get_pending_questions`, `confirm_pending_answer`) backed by `agent/knowledge/`.
    - `knowledge/` — Multi-agent knowledge system (see `specs/plan-multi-agent-knowledge.md`): one Strands domain agent per data source (Slack/Outlook/Teams/Fathom/Notion, plus I+D via its own MCP server) proposes entities/claims into a shared graph. A resolution ladder — `consult_knowledge_base` → `ask_peer_agents` (scoped Strands `Swarm` negotiation) → `escalate_or_validate` (human validation) — means agents only ask the human as a last resort, carrying a candidate answer when they have one. `store.py` (CRUD + `get_knowledge_stats` observability), `resolution.py` (find-or-create-entity, consult), `reconciliation.py` (cross-source duplicate detection + `same_as` merging via embedding similarity), `swarm_negotiation.py` (shared Swarm core), `domain_agent.py` (Document-table-backed agents + shared resolution-ladder tools), `rd_agent.py` (I+D platform agent via MCP, read-only), `scheduler.py` (`KnowledgeAgentScheduler` — opt-in periodic per-user cycle: every source, then reconciliation; not tied to `is_production` since every cycle costs real LLM calls).
  - `briefing/` — Daily briefing generator + scheduler
  - `sync/` — Server-side periodic sync scheduler (APScheduler)
  - `notion/` — Notion publisher, bidirectional sync, weekly digest, block parsing, workspace config

### CLI (`cli/`)
Terminal-based chat interface consuming the REST API:

- **`cli/main.py`** — Entry point, event loop, subcommands (login/logout/install)
- **`cli/auth.py`** — Login/logout flows for remote server authentication
- **`cli/onboarding.py`** — 5-step resumable onboarding wizard
- **`cli/chat.py`** — Main chat loop with agent queries
- **`cli/commands.py`** — Slash command router (16 commands: `/briefing`, `/sync`, `/commitments`, `/notion`, `/digest`, `/prep`, `/server`, etc.)
- **`cli/background.py`** — Periodic background sync + weekly digest scheduler
- **`cli/alerts.py`** — Proactive commitment alerts
- **`cli/notion_setup.py`** — Notion OAuth and workspace setup
- **`cli/api_client.py`** — Async httpx wrapper for all API calls (supports Bearer auth + X-User-Id)
- **`cli/config.py`** — Local config persistence (`~/.secondbrain/config.json`), file permissions security
- **`cli/display.py`** — Rich console formatting
- **`cli/server.py`** — Server lifecycle management (local mode only, guarded in remote mode)
- **`cli/installer.py`** — Local installation wizard (Docker, DB, migrations)
- **`cli/validators.py`** — Input validation helpers

### Connectors
| Connector | Class | Source | Data |
|---|---|---|---|
| Outlook | `MSGraphConnector` | `outlook` | Emails + calendar events |
| Teams | `TeamsConnector` | `teams` | 1:1 and group chat messages |
| Slack | `SlackConnector` | `slack` | Channel and DM messages |
| Fathom | `FathomConnector` | `fathom` | Meeting transcripts |
| Notion | `NotionConnector` | `notion` | Pages + database items |

### Notion Services (`app/services/notion/`)
| Module | Description |
|---|---|
| `publisher.py` | `NotionPublisher` — creates/updates pages and databases via Notion API |
| `sync.py` | `NotionSync` — bidirectional commitment sync with last-write-wins conflict resolution |
| `digest.py` | `WeeklyDigestGenerator` — generates weekly summary using Claude with fallback |
| `blocks.py` | Markdown-to-Notion block conversion and Notion block-to-text extraction |
| `config.py` | `NotionWorkspaceConfig` — workspace IDs (root page, databases) |

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

- `app/main.py` — Entry point, router registration, lifespan (starts sync scheduler)
- `app/core/config.py` — Settings (pydantic-settings, .env)
- `app/core/database.py` — Async engine, session factory
- `app/core/security.py` — API key authentication (Bearer token + bcrypt verification)
- `app/models/` — SQLAlchemy models (Base, UUIDMixin, TimestampMixin, APIKey)
- `app/api/routers/` — API endpoints (12 routers)
- `app/services/connectors/` — Platform connectors (5: outlook, teams, slack, fathom, notion)
- `app/services/agent/strands_orchestrator.py` — StrandsOrchestrator (main agent entry point)
- `app/services/agent/strands_tools.py` — Strands `@tool`-decorated wrappers around `tools/`
- `app/services/agent/knowledge/` — Multi-agent knowledge system: `store.py` (CRUD + observability), `domain_agent.py` (per-source Document agents), `rd_agent.py` (I+D platform via MCP), `resolution.py`, `reconciliation.py`, `swarm_negotiation.py`, `scheduler.py` (opt-in periodic knowledge cycles)
- `app/services/ingestion/pipeline.py` — Central data flow
- `app/services/retrieval/search.py` — Hybrid vector search
- `app/services/sync/scheduler.py` — APScheduler-based periodic sync
- `app/services/notion/` — Notion publisher, sync, digest
- `cli/` — CLI chat interface (16 slash commands, login/logout, installer)
- `pyproject.toml` — CLI package config (`pip install .` for remote-only installs)
- `Dockerfile` — Multi-stage build for deployment
- `.github/workflows/ci.yml` — CI pipeline (mypy + pytest)
- `.github/workflows/deploy.yml` — Build Docker image → GHCR → deploy via self-hosted runner
- `docker-compose.prod.yml` — Production stack (parameterized with --env-file)
- `infra/` — Deploy script, backup script, nginx config, systemd service, entrypoint
- `app/cli/create_api_key.py` — Bootstrap script for first API key
- `requirements.txt` — Dependencies
- `specs/` — Product specs, implementation plans, QA plan
- `tests/` — Unit, integration, and E2E tests
