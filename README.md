# secondBrain

A personal AI Chief of Staff that ingests your communications (email, chat, meetings), tracks commitments, generates daily briefings, and provides cross-platform RAG querying — all from a terminal interface.

## Features

- **Multi-platform ingestion** — Outlook, Teams, Slack, Fathom, and Notion
- **Commitment tracking** — AI-powered detection of promises, deadlines, and action items
- **Daily briefings** — Automated morning summaries with agenda, pending items, and alerts
- **RAG querying** — Ask questions across all your ingested data via semantic search
- **Notion integration** — Bidirectional sync of commitments, weekly digests, meeting prep
- **CLI chat interface** — Rich terminal UI with slash commands

## Quick Start

### Option 1: Connect to a remote server (fastest)

If you have a secondBrain server already deployed (e.g., Oracle Cloud VM):

```bash
# Install CLI only (no Docker/DB needed)
git clone https://github.com/rusitox/secondBrain.git
cd secondBrain
pip install .

# Login with your API key
secondbrain login

# Start chatting
secondbrain
```

Or use the installer with `--remote`:

```bash
./install.sh --remote
```

### Option 2: Automated local installer

```bash
# macOS / Linux — installs Docker, DB, and backend
curl -sSL https://raw.githubusercontent.com/rusitox/secondBrain/main/install.sh | bash

# Then start the CLI
python -m cli
```

### Option 3: Manual setup

#### Prerequisites

- Python 3.8+
- PostgreSQL 16+ with [pgvector](https://github.com/pgvector/pgvector) extension
- OpenAI API key (for embeddings)
- Anthropic API key (for Claude reasoning)

#### 1. Clone and install dependencies

```bash
git clone https://github.com/rusitox/secondBrain.git
cd secondBrain
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

#### 2. Set up the database

The easiest way is Docker:

```bash
docker compose up -d
```

This starts a `pgvector/pgvector:pg16` container on port 5432.

Or use an existing PostgreSQL instance with pgvector enabled:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Database
DATABASE_URL=postgresql+asyncpg://secondbrain:secondbrain_dev@localhost:5432/secondbrain
DATABASE_URL_SYNC=postgresql+psycopg2://secondbrain:secondbrain_dev@localhost:5432/secondbrain

# AI Models
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...

# Security — generate with the command below
FERNET_KEY=<your-key>
```

Generate a Fernet key:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

#### 4. Run database migrations

```bash
alembic upgrade head
```

#### 5. Start the server

```bash
python -m uvicorn app.main:app --reload
```

#### 6. Start the CLI

```bash
python -m cli
```

The CLI will walk you through onboarding: creating your account, connecting platforms, configuring your identity, and running the initial import.

## CLI Commands

| Command | Description |
|---------|-------------|
| `/briefing` | Show your daily briefing |
| `/commitments` | List pending commitments |
| `/overdue` | List overdue commitments |
| `/sync` | Sync all platforms (or `/sync slack` for one) |
| `/connect` | Connect a new platform |
| `/disconnect` | Disconnect a platform |
| `/status` | Show connection status and stats |
| `/identity` | View or edit your profile |
| `/settings` | View or edit preferences |
| `/setup` | Re-run onboarding wizard |
| `/notion` | Notion integration (connect, disconnect, status, sync, workspace) |
| `/digest` | Generate and publish weekly digest to Notion |
| `/prep <topic>` | Generate meeting prep (auto-publishes to Notion if connected) |
| `/server` | Server management (start, stop, restart, status, logs) |
| `/help` | Show available commands |
| `/quit` | Exit secondBrain |

**Subcommands:**

| Command | Description |
|---------|-------------|
| `secondbrain login` | Authenticate against a remote server |
| `secondbrain logout` | Clear stored credentials |
| `secondbrain install` | Run the local installer |

Any other input is treated as a natural language question and routed to the AI agent for RAG-powered answers.

## Notion Integration

Connect Notion to get bidirectional commitment sync, daily briefings, weekly digests, and meeting prep published as Notion pages.

```
/notion connect    # Authenticate with Notion API token
/notion workspace  # Open your secondBrain workspace in Notion
/notion sync       # Trigger manual commitment sync
/notion status     # Check connection status
/digest            # Generate and publish weekly digest
/prep Q3 Planning  # Generate meeting prep and publish to Notion
```

During setup, secondBrain creates three databases in your Notion workspace:
- **Commitments** — Tracks all detected promises and action items
- **Daily Briefings** — Stores daily briefings and weekly digests
- **Meeting Prep** — Stores meeting preparation documents

## Architecture

```
Sources (Outlook/Teams/Slack/Fathom/Notion)
    ↓
FastAPI Ingestion Pipeline → Clean → Chunk → Embed → PostgreSQL+pgvector
    ↓
Commitment Detection (Claude) → Commitments table
    ↓
CLI Chat ←→ REST API ←→ RAG Agent (Claude + tools)
    ↓
Daily Briefing / Weekly Digest / Meeting Prep → Notion
```

### Backend (`app/`)

| Layer | Path | Description |
|-------|------|-------------|
| Core | `app/core/` | Config, database, security, logging |
| Models | `app/models/` | User, Identity, Integration, Document, Commitment, APIKey |
| API | `app/api/routers/` | 13 REST routers (health, users, commitments, integrations, ingestion, query, agent, briefing, identity, sync, auth, voice, knowledge) |
| Auth | `app/core/security.py` | API key authentication (Bearer token, bcrypt) |
| Connectors | `app/services/connectors/` | Outlook, Teams, Slack, Fathom, Notion |
| Ingestion | `app/services/ingestion/` | Cleaner, chunker, embedder, pipeline |
| Retrieval | `app/services/retrieval/` | Semantic search with metadata filters |
| LLM | `app/services/llm/` | Claude client + prompt templates |
| Commitments | `app/services/commitments/` | AI-powered commitment detection |
| Agent | `app/services/agent/` | Strands Agent (AWS Strands Agents framework) with tool-use loop |
| Knowledge | `app/services/agent/knowledge/` | Multi-agent knowledge graph: one domain agent per data source proposes entities/claims, resolving doubts via peer-agent negotiation before ever asking the human |
| Briefing | `app/services/briefing/` | Daily briefing generator + scheduler |
| Sync | `app/services/sync/` | Server-side periodic sync (APScheduler) |
| Notion | `app/services/notion/` | Publisher, sync, digest, blocks, config |

### CLI (`cli/`)

| Module | Description |
|--------|-------------|
| `main.py` | Entry point, subcommands (login/logout/install) |
| `auth.py` | Login/logout flows for remote server auth |
| `chat.py` | Main chat loop with agent queries |
| `commands.py` | Slash command router (16 commands) |
| `onboarding.py` | 5-step resumable onboarding wizard |
| `background.py` | Periodic background sync + digest scheduler |
| `alerts.py` | Proactive commitment alerts |
| `notion_setup.py` | Notion integration setup |
| `api_client.py` | Async httpx wrapper (Bearer auth + X-User-Id) |
| `config.py` | Local config persistence (`~/.secondbrain/config.json`) |
| `display.py` | Rich console formatting |
| `server.py` | Server lifecycle management (local mode only) |
| `installer.py` | Local installation wizard |
| `validators.py` | Input validation helpers |

## Development

```bash
# Run all tests
pytest tests/

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Coverage report
pytest --cov=app --cov-report=term-missing

# Type checking
mypy app/ cli/ --ignore-missing-imports
```

### Project Structure

```
secondBrain/
├── app/                    # FastAPI backend
│   ├── core/               # Config, database, security (API key auth)
│   ├── models/             # SQLAlchemy models (User, APIKey, etc.)
│   ├── api/
│   │   ├── routers/        # REST endpoints (13 routers)
│   │   └── schemas/        # Pydantic models
│   └── services/
│       ├── connectors/     # Platform connectors (5)
│       ├── ingestion/      # Data pipeline
│       ├── retrieval/      # Semantic search
│       ├── llm/            # Claude client
│       ├── commitments/    # Commitment detection
│       ├── agent/          # Strands agent + multi-agent knowledge graph
│       ├── briefing/       # Daily briefings
│       ├── sync/           # Server-side periodic sync
│       └── notion/         # Notion publisher, sync, digest
├── cli/                    # Terminal chat interface + auth + installer
├── alembic/                # Database migrations (6 revisions)
├── specs/                  # Product specs and plans
├── tests/                  # Unit and integration tests
├── Dockerfile              # Multi-stage build for deployment
├── docker-compose.yml      # PostgreSQL + pgvector
├── pyproject.toml          # CLI package config (pip install .)
├── .github/workflows/      # CI/CD (build + push to GHCR)
├── requirements.txt        # Python dependencies
└── .env.example            # Environment template
```

## Deployment

### Cloud deployment (Oracle Cloud / any VPS)

The server runs as a Docker container with PostgreSQL + pgvector:

```bash
# On the server
docker compose up -d                  # Start DB + backend
alembic upgrade head                  # Run migrations
```

CI/CD via GitHub Actions automatically builds and pushes to GHCR on every push to `main`.

### Remote CLI access

From any machine, install just the CLI and connect to your server:

```bash
pip install .              # Install CLI package (lightweight: httpx, rich, prompt-toolkit)
secondbrain login          # Authenticate with API key
secondbrain                # Start chatting
```

API keys are created server-side and use the format `sb_live_<hex>`. Keys are bcrypt-hashed in the database; only the key prefix (12 chars) is stored in plaintext for lookup.

## License

Private project.
