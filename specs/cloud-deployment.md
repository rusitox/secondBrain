# Cloud Deployment — Multi-Device Access

**Status:** Draft  
**Author:** Architecture Review  
**Date:** 2026-04-19

## Goal

Enable secondBrain to be accessible from any of Mariano's devices without requiring a local PostgreSQL instance, a local FastAPI server, or project source code on every machine.

---

## Current Architecture Inventory

### What is local today

| Component | Location | Notes |
|---|---|---|
| PostgreSQL + pgvector | Docker container (`secondbrain-db`) on localhost:5432 | Data lives in `secondbrain-data` Docker volume |
| FastAPI server | `python -m uvicorn app.main:app` on localhost:8000 | Spawned by `cli/server.py` as a background process |
| CLI config | `~/.secondbrain/config.json` | user_id, server_url, onboarding state, Notion config, platform list |
| CLI itself | `python -m cli` from project checkout | Requires full repo clone + `pip install -r requirements.txt` |
| Platform tokens | Encrypted (Fernet) in PostgreSQL `integrations.access_token` | Fernet key in `.env` — same key needed on every machine |
| Background sync | `cli/background.py` — runs in CLI's asyncio loop | Sync only happens while CLI is running |
| Alerts | `cli/alerts.py` — in-memory queue inside CLI | Lost when CLI exits |
| Briefing scheduler | `app/services/briefing/scheduler.py` — APScheduler in-process | Only runs while server is up |
| Server PID/logs | `~/.secondbrain/server.pid`, `~/.secondbrain/server.log` | Local process management |
| `.env` file | Project root | DATABASE_URL, FERNET_KEY, OPENAI_API_KEY, CLAUDE_API_KEY |

### What is already remote-ready

| Component | Why |
|---|---|
| CLI <-> Backend communication | `cli/api_client.py` is already a pure HTTP client; `server_url` is configurable |
| Auth header | `X-User-Id` header is all that's needed (weak, but the plumbing exists) |
| Data model | All state is in PostgreSQL; no SQLite or local files used by the backend |
| Encryption | Fernet key is a server-side env var; CLI never touches tokens directly |

### Key coupling points

1. **`cli/server.py`** — CLI assumes it manages the server lifecycle (start/stop/restart). This becomes irrelevant with a remote server.
2. **`cli/config.py`** — Stores `server_url=http://localhost:8000` by default. Also stores onboarding state and Notion config that should ideally be server-side.
3. **`install.sh`** — Assumes local Docker + full repo checkout.
4. **Background sync** — Currently client-side. If no CLI is running, nothing syncs.
5. **Auth** — `X-User-Id` is a UUID passed as a header. No authentication, no authorization. Anyone who can reach the server can impersonate any user.

---

## Options Analysis

### Option A: Cloud-Hosted Backend (Managed PaaS)

Deploy FastAPI + PostgreSQL to a managed platform (Railway, Render, or Fly.io). CLI remains a local thin client pointing to the remote URL.

**How it works:**
- PostgreSQL+pgvector on Supabase (already configured in `app/core/config.py` with `supabase_url`/`supabase_key`) or Railway's Postgres addon
- FastAPI deployed as a container or buildpack on Railway/Render/Fly
- CLI installed via `pip install secondbrain-cli` (or `pipx`) on any machine, configured with `secondbrain login`

**Code changes required:**
| Change | Scope | Files |
|---|---|---|
| Add `Dockerfile` for the API server | Small | New: `Dockerfile` |
| Add production config (CORS, trusted origins) | Small | `app/main.py`, `app/core/config.py` |
| Add JWT/API-key auth to replace `X-User-Id` | Medium | `app/core/security.py`, `app/api/deps.py`, new `app/api/routers/auth.py` |
| Move background sync to server-side (cron/scheduler) | Medium | New: `app/services/sync/scheduler.py`, modify `app/main.py` lifespan |
| Move CLI-local state to server (onboarding, Notion config, preferences) | Medium | `cli/config.py`, new API endpoints on `app/api/routers/users.py` |
| Package CLI as standalone `pip install` package | Medium | New: `cli/setup.py` or `pyproject.toml` for CLI |
| Add `secondbrain login` flow (API key or email+password) | Medium | `cli/main.py`, `cli/config.py` |
| Make `cli/server.py` optional (skip local server management when remote) | Small | `cli/server.py`, `cli/main.py` |

**Pros:**
- Zero infrastructure management
- Always-on server = background sync works 24/7
- Free/cheap tiers available (Railway: $5/mo, Render: free tier, Supabase: free tier)
- CLI becomes a 5-minute install on any machine

**Cons:**
- Monthly cost ($5-20/mo for always-on server + DB)
- Data on third-party infrastructure
- Cold starts on free tiers (Render spins down after 15min idle)
- Vendor lock-in for deployment specifics

**UX from a new machine:**
```bash
pip install secondbrain-cli
secondbrain login          # enters API key or email
secondbrain chat           # immediately works
```

### Option B: Self-Hosted VPS

Run the full stack on a VPS (DigitalOcean droplet, Hetzner, home server). CLI connects remotely.

**Code changes:** Same as Option A (auth, Dockerfile, sync migration, CLI packaging).

**Additional work:**
| Change | Scope |
|---|---|
| Write deployment scripts (systemd unit, nginx reverse proxy, Let's Encrypt) | Medium |
| Document manual server setup | Small |
| Handle dynamic DNS if home server | Small |

**Pros:**
- Full data sovereignty
- Potentially cheaper ($4-6/mo for a small VPS)
- No cold starts

**Cons:**
- Manual ops burden (updates, backups, SSL renewal, monitoring)
- Need to handle uptime, security patches, firewall
- Same code changes as Option A plus deployment automation

### Option C: Containerized "One-Command" Deployment

Full Docker Compose stack (API + DB + nginx) deployable to any Docker host.

**Code changes:** Same as Option A, plus:
| Change | Scope |
|---|---|
| Extend `docker-compose.yml` with `api` and `nginx` services | Small |
| Add `Dockerfile` for API | Small |
| Add nginx config with SSL termination | Small |
| Add `docker-compose.prod.yml` overlay | Small |

**Pros:**
- Portable — works on any Docker host (VPS, NAS, cloud VM)
- Reproducible environment
- Easy to backup (volume snapshots)

**Cons:**
- Still requires a machine to run Docker on
- Same ops burden as Option B
- Docker Compose is not a production orchestrator

### Option D: Hybrid (Recommended)

Cloud backend + installable CLI with zero-config login. Specifically:

1. **Backend on Railway** (or Render) — FastAPI container + Railway Postgres (with pgvector)
2. **CLI as a pip package** — `pip install secondbrain-cli`
3. **Server-side background sync** — syncs run on a schedule even when no CLI is connected
4. **API key auth** — user gets an API key during onboarding, CLI stores only `{server_url, api_key}` locally
5. **All user state server-side** — onboarding progress, Notion config, preferences stored in the User model or a new UserPreferences table

This is Option A with explicit architectural decisions baked in.

---

## Recommendation: Option D (Hybrid)

### Justification

1. **Minimal ops burden** — managed PaaS handles infra; Mariano focuses on the product
2. **Background sync independence** — syncs happen server-side on a cron, not only when CLI is open
3. **Multi-device with no state sync** — the CLI is stateless beyond `{url, api_key}`; any machine works immediately
4. **Migration path to Option B/C** — the Dockerfile and auth changes are the same; switching from Railway to a VPS later is a container move, not a rewrite
5. **Cost** — Railway Hobby plan: ~$5/mo; Supabase free tier for Postgres; total ~$5-10/mo

### What Needs to Change

#### Phase 1: Authentication (Medium complexity)

Replace `X-User-Id` header with API key authentication.

- [ ] Create `app/models/api_key.py` — `APIKey` model (id, user_id, key_hash, name, created_at, last_used_at, is_active)
- [ ] Add `POST /auth/api-keys` endpoint — generate API key, return it once, store bcrypt hash
- [ ] Add `DELETE /auth/api-keys/{key_id}` endpoint — revoke a key
- [ ] Modify `app/core/security.py` — `get_current_user_id()` reads `Authorization: Bearer sb_...` header, looks up key hash in DB
- [ ] Add `app/api/routers/auth.py` — auth endpoints
- [ ] Update `app/api/deps.py` — wire new auth dependency
- [ ] Keep `X-User-Id` as a fallback for `app_env=development` only
- [ ] Alembic migration for `api_keys` table

**Files:** `app/models/api_key.py` (new), `app/core/security.py`, `app/api/deps.py`, `app/api/routers/auth.py` (new), `app/main.py`

#### Phase 2: Server-Side Sync (Medium complexity)

Move background sync from CLI to server. The CLI should not need to be running for syncs to happen.

- [ ] Create `app/services/sync/scheduler.py` — server-side sync scheduler using APScheduler (already a dependency pattern in `briefing/scheduler.py`)
- [ ] Add sync configuration to User model or new `SyncConfig` table (interval, last_run, enabled platforms)
- [ ] Add `POST /sync/configure` endpoint — set sync interval and platforms
- [ ] Add `GET /sync/status` endpoint — last sync times, next scheduled run
- [ ] Wire scheduler into `app/main.py` lifespan (start on startup, shutdown on exit)
- [ ] Keep `POST /ingest/sync/{platform}` for on-demand sync from CLI
- [ ] `cli/background.py` becomes optional — only used for local-mode development

**Files:** `app/services/sync/scheduler.py` (new), `app/api/routers/sync.py` (new), `app/main.py`, `cli/background.py`

#### Phase 3: Server-Side User State (Medium complexity)

Move onboarding state, preferences, and Notion config from `~/.secondbrain/config.json` to the server.

- [ ] Extend `User` model (or new `UserPreferences` model) with: `onboarding_completed`, `onboarding_step`, `preferences` (JSONB), `notion_config` (JSONB)
- [ ] Add `GET/PATCH /users/{id}/preferences` endpoints
- [ ] Add `GET/PATCH /users/{id}/notion-config` endpoints
- [ ] Modify `cli/config.py` — `CLIConfig` becomes minimal: `server_url`, `api_key`, `user_id` (cached). Everything else fetched from server.
- [ ] Modify `cli/onboarding.py` — read/write state via API instead of local config
- [ ] Alembic migration for new columns

**Files:** `app/models/user.py`, `app/api/routers/users.py`, `app/api/schemas/user.py`, `cli/config.py`, `cli/onboarding.py`, `cli/commands.py`

#### Phase 4: Dockerfile and Deployment (Small complexity)

- [ ] Create `Dockerfile` — multi-stage build, Python 3.11, copy app/, run uvicorn
- [ ] Create `docker-compose.prod.yml` — API + Postgres + optional nginx
- [ ] Add CORS configuration to `app/main.py` (allow CLI from any origin — it's not browser-based, but good hygiene)
- [ ] Add `app_env=production` guards: disable debug, require HTTPS for token endpoints, rate limiting
- [ ] Create `railway.toml` or `Procfile` for Railway deployment
- [ ] Add health check endpoint improvements (DB connectivity check for Railway)

**Files:** `Dockerfile` (new), `docker-compose.prod.yml` (new), `railway.toml` (new), `app/main.py`, `app/core/config.py`

#### Phase 5: CLI Packaging and Login Flow (Medium complexity)

- [ ] Create `cli/pyproject.toml` — package the CLI as `secondbrain-cli` with entry point `secondbrain`
- [ ] Add `secondbrain login` command — prompt for server URL + API key, store in `~/.secondbrain/config.json`
- [ ] Add `secondbrain logout` command — clear local credentials
- [ ] Modify `cli/main.py` — skip local server management when `server_url` is not localhost
- [ ] Modify `cli/server.py` — make all local server management conditional on `is_local_mode()`
- [ ] Update `install.sh` — add a `--remote` flag that skips Docker/server setup and just does `pip install` + `secondbrain login`

**Files:** `cli/pyproject.toml` (new), `cli/main.py`, `cli/server.py`, `cli/config.py`, `install.sh`

---

### Migration Path

**From current local setup to cloud:**

1. Deploy backend to Railway (Phase 4)
2. Run Alembic migrations against cloud Postgres (same schema, new instance)
3. Export local Postgres data: `pg_dump secondbrain > backup.sql` then import to cloud DB
4. Re-encrypt tokens: if using a new `FERNET_KEY`, old tokens are unreadable. Either:
   - Use the same `FERNET_KEY` in cloud `.env` (simplest)
   - Write a migration script that decrypts with old key, re-encrypts with new key
5. Generate an API key for the user via the new auth endpoint
6. On each device: `pip install secondbrain-cli && secondbrain login`
7. Local Docker can be torn down

**Backward compatibility:**
- The server continues to accept `X-User-Id` in development mode, so existing tests and local dev workflows are unaffected
- `cli/server.py` still works for local development — it just isn't used when pointing to a remote server
- `docker-compose.yml` (local DB only) remains unchanged; `docker-compose.prod.yml` is additive

---

### Risks and Considerations

| Risk | Severity | Mitigation |
|---|---|---|
| **API key leaked = full account access** | High | Keys are hashed (bcrypt) in DB; add key rotation and revocation; consider short-lived JWT tokens as a future improvement |
| **Network latency for CLI** | Low | CLI already uses async httpx with generous timeouts; RAG queries already take seconds (LLM round-trip) |
| **Fernet key management in cloud** | Medium | Store as Railway secret; document that changing it invalidates all stored platform tokens |
| **Railway free tier cold starts** | Medium | Use Hobby plan ($5/mo) for always-on; or accept 10-30s first-request delay on free tier |
| **Data migration from local PG** | Low | Standard pg_dump/pg_restore; pgvector data exports cleanly |
| **Background sync rate limits** | Medium | Platform APIs (MS Graph, Slack) have rate limits; server-side scheduler should respect them and back off |
| **Single point of failure** | Medium | Railway has good uptime; for critical use, add health monitoring and alerts |

---

### Cost Estimate

| Service | Plan | Monthly Cost |
|---|---|---|
| Railway (FastAPI) | Hobby | ~$5 |
| Railway Postgres (or Supabase) | Free/Hobby | $0-5 |
| Domain (optional) | Cloudflare | ~$1 |
| **Total** | | **$5-11/mo** |

---

### Scope Summary

| Phase | Complexity | Estimated Effort |
|---|---|---|
| Phase 1: Authentication | Medium | 2-3 days |
| Phase 2: Server-side sync | Medium | 2-3 days |
| Phase 3: Server-side state | Medium | 2-3 days |
| Phase 4: Dockerfile + deploy | Small | 1-2 days |
| Phase 5: CLI packaging + login | Medium | 2-3 days |
| **Total** | | **9-14 days** |

Phases 1 and 4 can be done in parallel. Phase 3 depends on Phase 1 (auth). Phase 5 depends on Phase 4 (needs a deployed server to test against).

---

### Architectural Questions — Resolved

**Should background sync run server-side?**  
Yes. This is the single biggest UX win. Currently, data only syncs when the CLI is open. Server-side sync means commitments are detected, emails are indexed, and briefings are generated even when Mariano is not at a terminal.

**How should authentication work?**  
API keys (Phase 1). The current `X-User-Id` header is a development placeholder. API keys are simple, stateless, and work well for a single-user CLI tool. JWT tokens add complexity (refresh flows, expiry) that is not needed for this use case. API keys can be revoked and rotated.

**Should CLI config be server-side?**  
Most of it, yes (Phase 3). The CLI should only store: `server_url`, `api_key`, and a cached `user_id`. Onboarding state, platform connections, Notion config, and preferences should live on the server so any CLI instance sees the same state.

**What about Notion workspace config?**  
Moves to server-side `UserPreferences` or a dedicated JSONB column. The CLI fetches it on demand rather than reading from local disk. The Notion API token is already stored as an Integration in the DB; only the workspace-specific IDs (database IDs, etc.) need to move.

---

### Files to Create

- `Dockerfile`
- `docker-compose.prod.yml`
- `railway.toml` (or `Procfile`)
- `app/models/api_key.py`
- `app/api/routers/auth.py`
- `app/api/routers/sync.py`
- `app/services/sync/scheduler.py`
- `cli/pyproject.toml`
- Alembic migrations (2-3)

### Files to Modify

- `app/core/security.py` — API key auth
- `app/core/config.py` — production settings (CORS origins, allowed hosts)
- `app/api/deps.py` — new auth dependency
- `app/main.py` — CORS, lifespan (sync scheduler), auth router
- `app/models/user.py` — preferences/config columns
- `app/api/routers/users.py` — preferences endpoints
- `app/api/schemas/user.py` — preferences schemas
- `cli/config.py` — minimal local config
- `cli/main.py` — remote mode, login command
- `cli/server.py` — conditional local mode
- `cli/onboarding.py` — API-backed state
- `cli/commands.py` — fetch config from server
- `cli/background.py` — optional in remote mode
- `install.sh` — `--remote` flag
