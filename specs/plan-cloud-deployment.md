# Plan: Oracle Cloud VPS Deployment

**Status:** Draft
**Author:** Architecture Review
**Date:** 2026-04-19
**Depends on:** `specs/cloud-deployment.md` (analysis)

---

## Goal

Deploy secondBrain to an Oracle Cloud free-tier ARM VM with Docker Compose and nginx (behind Tailscale), then adapt the CLI to connect remotely with API key authentication.

## Scope

- **IN:** API key auth, server-side sync, server-side user state, Docker containerization for Oracle Cloud VPS, GitHub Actions CI/CD (build + push to GHCR), nginx reverse proxy (HTTP only — Tailscale handles encryption), systemd service, CLI login flow, CLI pip packaging
- **OUT:** Multi-user support (this is single-user), Terraform/IaC automation (manual VM provision), SSL/TLS certificates (Tailscale provides end-to-end encryption), mobile/web client

---

## Phase Ordering Decision

The original spec suggests phases 1-5 in order. For Oracle Cloud VPS, we reorder:

**Phase 4 (Containerization) -> Phase 1 (Auth) -> Phase 2 (Server Sync) -> Phase 3 (Server State) -> Phase 5 (CLI Packaging)**

Rationale:
1. **Phase 4 first** because we need a deployed server to test against. Containerization has zero dependencies on the other phases — the current codebase runs fine in Docker as-is.
2. **Phase 1 next** to establish proper API key auth. Although Tailscale keeps the server private, API keys enable multi-device identity and are required for the CLI login flow.
3. **Phases 2 and 3** build on Phase 1 (auth is a prerequisite for all new endpoints).
4. **Phase 5 last** because it needs a deployed, authenticated server to test the login flow end-to-end.

We add a **Phase 0** for Oracle Cloud VM provisioning (manual, but documented).

---

## Phase 0: Oracle Cloud VM Provisioning — COMPLETE

### Status: Done (pre-existing VM)

The Oracle Cloud ARM VM already exists and runs another API. Infrastructure is in place:

- [x] Oracle Cloud free-tier ARM VM provisioned
- [x] Docker Engine + Docker Compose installed and running
- [x] Ports open in OCI security lists
- [x] Nginx running (shared with other API)
- [x] **Tailscale** provides point-to-point encrypted networking between all devices

### Tailscale Impact on Architecture

Tailscale uses WireGuard to create an encrypted mesh network. This changes several assumptions:

1. **No SSL/Let's Encrypt needed** — Tailscale traffic is already encrypted end-to-end. Nginx proxies as plain HTTP within the tailnet.
2. **No public internet exposure** — The server is only reachable from devices on the tailnet. This eliminates the attack surface that made Phase 1 (auth) urgent.
3. **Simplified nginx** — No port 443, no certificate management, no HSTS. Just a `server` block proxying to the API container.
4. **DNS is Tailscale MagicDNS** — Access via `<hostname>` or Tailscale IP, no need for a public domain or A records.
5. **Phase 1 (auth) is still recommended** — even in a private network, API key auth prevents accidental misuse and enables multi-device identity. But it's not a security emergency.

### What remains for Phase 4
- Add a server block to the **existing** nginx for secondbrain (not install a new nginx)
- No SSL config, no certbot, no `init-ssl.sh`
- No `secondbrain-initial.conf` (HTTP-only for cert issuance) — not needed

---

## Phase 4: Containerization and Deployment (Reordered to execute first)

### Goal
Package the FastAPI app as a Docker image, set up Docker Compose with PostgreSQL, and configure the existing nginx on the VM to reverse-proxy to the container (plain HTTP — Tailscale encrypts the transport).

### Estimated complexity: Medium
### Dependencies: Phase 0 (VM exists, Docker installed, Tailscale connected)

### Tasks

#### 4.1 Create `Dockerfile`

**File:** `Dockerfile` (new, project root)

Multi-stage build for the FastAPI API server:
- **Stage 1 (builder):** `python:3.11-slim-bookworm` as base. Install build deps (`gcc`, `libpq-dev`). Copy `requirements.txt`, run `pip install --no-cache-dir`. This stage is discarded.
- **Stage 2 (runtime):** `python:3.11-slim-bookworm` as base. Install only `libpq5` (runtime dep for asyncpg). Copy installed packages from builder. Copy `app/` and `alembic/` and `alembic.ini`. Set `PYTHONPATH=/app`. Run as non-root user (`appuser`). Expose port 8000.
- **Entrypoint:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`
- **Note on ARM:** `python:3.11-slim-bookworm` has official `linux/arm64` images. The `pgvector` Python package is pure Python (wraps SQL), so no cross-compile issues. `asyncpg` builds fine on ARM.
- **Health check:** `HEALTHCHECK CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"` or use `curl`.

#### 4.2 Create `docker-compose.prod.yml`

**File:** `docker-compose.prod.yml` (new, project root)

Three services:

**`db` service:**
- Image: `pgvector/pgvector:pg16` (has ARM64 images)
- Volumes: `secondbrain-pgdata:/var/lib/postgresql/data`
- Environment: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` from `.env.prod`
- NO port mapping (only accessible from within Docker network) -- this is a security improvement over the dev compose file
- Healthcheck: `pg_isready -U secondbrain`

**`api` service:**
- Image: `ghcr.io/rusitox/secondbrain:latest` (pulled from GHCR, built by GitHub Actions)
- Depends on: `db` (healthy)
- Environment: reads from `.env.prod` file
  - `DATABASE_URL=postgresql+asyncpg://secondbrain:${DB_PASSWORD}@db:5432/secondbrain`
  - `DATABASE_URL_SYNC=postgresql://secondbrain:${DB_PASSWORD}@db:5432/secondbrain`
  - `APP_ENV=production`
  - `FERNET_KEY`, `OPENAI_API_KEY`, `CLAUDE_API_KEY` from `.env.prod`
- Port: `8000:8000` on the host — nginx on the host proxies to this port
- Restart: `unless-stopped`
- Healthcheck: `curl -f http://localhost:8000/health || exit 1`
- Entrypoint script runs `alembic upgrade head` then starts uvicorn

**No nginx service in Docker Compose** — the VM's existing nginx handles reverse-proxying. The API container exposes port 8000 to the host, and nginx forwards to it.

**Volumes:** `secondbrain-pgdata`

**Networks:** Default bridge network is sufficient (db and api can reach each other by service name).

#### 4.3 Create nginx configuration

**File:** `infra/nginx/secondbrain.conf` (new)

Server block to add to the **existing** nginx on the VM (not a standalone nginx):

- `server_name secondbrain;` (or Tailscale hostname)
- `listen 8080;` (pick a port not used by the other API; nginx on the host proxies to the Docker container)
- `location /` proxies to `http://127.0.0.1:8000` with standard proxy headers (`X-Real-IP`, `X-Forwarded-For`)
- Client max body size: `10m` (for ingestion payloads)
- Gzip: enabled for JSON responses

**No SSL needed** — Tailscale encrypts all traffic end-to-end via WireGuard.

**Deployment:** Copy this file to `/etc/nginx/sites-enabled/secondbrain.conf` on the VM and `nginx -s reload`.

#### 4.4 Create entrypoint script

**File:** `infra/docker-entrypoint.sh` (new)

Shell script used as the Docker entrypoint for the `api` container:
1. Wait for database to be reachable (retry loop with `pg_isready` or Python check)
2. Run `alembic upgrade head` to apply any pending migrations
3. Exec into `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`

This ensures migrations run automatically on every deployment.

#### 4.5 Create `.env.prod.example`

**File:** `.env.prod.example` (new)

Template for production environment variables:
```
APP_ENV=production
DB_PASSWORD=<generate-strong-password>
DATABASE_URL=postgresql+asyncpg://secondbrain:${DB_PASSWORD}@db:5432/secondbrain
DATABASE_URL_SYNC=postgresql://secondbrain:${DB_PASSWORD}@db:5432/secondbrain
FERNET_KEY=<generate-with-python>
OPENAI_API_KEY=<your-key>
CLAUDE_API_KEY=<your-key>
```

Add `.env.prod` to `.gitignore`.

#### 4.6 Create GitHub Actions workflow

**File:** `.github/workflows/build-and-push.yml` (new)

GitHub Actions workflow that builds the Docker image and pushes to GHCR:

**Trigger:** Push to `main` branch (only when `app/`, `requirements.txt`, `Dockerfile`, or `alembic/` change)

**Steps:**
1. Checkout code
2. Set up Docker Buildx
3. Login to GHCR (`ghcr.io`) using `GITHUB_TOKEN`
4. Build multi-platform image (`linux/amd64,linux/arm64`) — ARM64 for Oracle Cloud, AMD64 for local testing
5. Tag as `ghcr.io/rusitox/secondbrain:latest` and `ghcr.io/rusitox/secondbrain:<sha-short>`
6. Push to GHCR

**Note:** `GITHUB_TOKEN` has built-in write access to GHCR for the same repo. No additional secrets needed.

#### 4.7 Create deployment script

**File:** `infra/deploy.sh` (new)

Lightweight script to pull the latest image and restart on the VM:
1. Accept `--host` argument (default: Tailscale hostname of the VM)
2. SSH into the VM and run:
   - `cd /opt/secondbrain`
   - `docker compose -f docker-compose.prod.yml pull`
   - `docker compose -f docker-compose.prod.yml up -d`
3. Verify deployment: `curl -f http://localhost:8000/health`

No `rsync` needed — the image comes from GHCR. Only `docker-compose.prod.yml`, `.env.prod`, and `infra/` files need to be on the VM (one-time setup).

#### 4.8 Create systemd service

**File:** `infra/secondbrain.service` (new)

Systemd unit file to install at `/etc/systemd/system/secondbrain.service`:
```ini
[Unit]
Description=secondBrain Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/secondbrain
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

This ensures secondBrain starts on VM reboot.

#### 4.9 Modify `app/main.py` -- production guards

**File:** `app/main.py` (modify)

Add to the `lifespan` function:
- If `app_env == "production"`, log a warning if no API key auth is configured (until Phase 1 is done)
- Add CORS middleware: in production, no browser origins needed (CLI uses direct HTTP), but set restrictive defaults. In development, allow `localhost:*`.

**File:** `app/core/config.py` (modify)

Add settings:
- `cors_origins: str = ""` -- comma-separated list of allowed origins
- `allowed_hosts: str = ""` -- for trusted host middleware (optional)

#### 4.10 Modify `app/api/routers/health.py` -- enhanced health check

**File:** `app/api/routers/health.py` (modify)

Add a `/health/detailed` endpoint (authenticated, for monitoring) that checks:
- Database connectivity (run a simple SELECT 1)
- Disk space on the data volume (optional, nice-to-have)
- Return uptime, version, environment

Keep the existing `/health` endpoint as a simple 200 OK for nginx/Docker health checks.

#### 4.11 Create backup script


**File:** `infra/backup.sh` (new)

Automated PostgreSQL backup script:
1. Run `pg_dump` inside the `db` container
2. Compress with gzip
3. Store in `/opt/secondbrain/backups/` with timestamp filename
4. Delete backups older than 30 days
5. Intended to run via cron: `0 3 * * * /opt/secondbrain/infra/backup.sh`

### Files to create (Phase 4):
| File | Purpose |
|---|---|
| `Dockerfile` | API server container (multi-stage, ARM64-compatible) |
| `docker-compose.prod.yml` | Production stack (db + api, image from GHCR) |
| `.github/workflows/build-and-push.yml` | CI: build Docker image + push to GHCR |
| `infra/nginx/secondbrain.conf` | Nginx server block (HTTP reverse proxy for host nginx) |
| `infra/docker-entrypoint.sh` | Migration + startup script |
| `infra/deploy.sh` | Pull + restart on VM (via Tailscale SSH) |
| `infra/backup.sh` | PostgreSQL backup cron |
| `infra/secondbrain.service` | Systemd unit |
| `.env.prod.example` | Env var template |

### Files to modify (Phase 4):
| File | Change |
|---|---|
| `app/main.py` | CORS middleware, production guards |
| `app/core/config.py` | `cors_origins`, `allowed_hosts` settings |
| `app/api/routers/health.py` | Enhanced health check |
| `.gitignore` | Add `.env.prod`, `backups/` |

### Testing strategy (Phase 4):
1. **Local:** `docker build -t secondbrain:test .` succeeds on ARM Mac (same arch as OCI)
2. **Local:** `docker compose -f docker-compose.prod.yml up` and `curl http://localhost:8000/health` returns 200
3. **CI:** Push to `main`, verify GitHub Actions builds and pushes to `ghcr.io/rusitox/secondbrain:latest`
4. **VM:** `infra/deploy.sh` pulls new image, verify `curl http://<tailscale-hostname>:8080/health` returns 200 (via nginx)
5. **VM:** Verify systemd service: `sudo systemctl restart secondbrain && curl http://localhost:8000/health`
6. **VM:** Verify backup script runs: `sudo /opt/secondbrain/infra/backup.sh && ls -la /opt/secondbrain/backups/`

---

## Phase 1: Authentication (API Keys)

### Goal
Replace `X-User-Id` header with `Authorization: Bearer sb_...` API key authentication. While Tailscale keeps the server off the public internet, API key auth enables proper multi-device identity and prevents accidental misuse.

### Estimated complexity: Medium
### Dependencies: Phase 4 (server is deployed)

### Key Design Decisions

**API key format:** `sb_live_<32-random-hex>` (40 chars total)
- Prefix `sb_live_` makes keys greppable in logs/code to detect accidental exposure
- 32 hex chars = 128 bits of entropy (more than sufficient)
- Example: `sb_live_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6`

**Storage:** bcrypt hash in the database
- bcrypt over argon2: simpler, no extra dependency (use `passlib` or `bcrypt` package -- add to `requirements.txt`)
- Store the first 8 chars of the key as a `key_prefix` column for identification without hash comparison
- On key creation, return the full key exactly once; only store the hash

**Fallback:** In `app_env=development`, continue accepting `X-User-Id` header so tests and local dev work without API keys.

### Tasks

#### 1.1 Create `APIKey` model

**File:** `app/models/api_key.py` (new)

SQLAlchemy model:
- `id: UUID` (UUIDMixin)
- `user_id: UUID` (ForeignKey to `users.id`)
- `key_hash: str` (String(255), not null) -- bcrypt hash of the full key
- `key_prefix: str` (String(10), not null) -- first 8 chars for display/identification
- `name: str` (String(100), not null) -- human label like "macbook" or "work-laptop"
- `last_used_at: Optional[datetime]` (DateTime, nullable)
- `is_active: bool` (Boolean, default True)
- Inherits `TimestampMixin` for `created_at`/`updated_at`
- Relationship: `user` back to `User`

**File:** `app/models/__init__.py` (modify) -- add `APIKey` to exports

**File:** `app/models/user.py` (modify) -- add `api_keys` relationship

#### 1.2 Create auth schemas

**File:** `app/api/schemas/auth.py` (new)

Pydantic models:
- `APIKeyCreate` -- request: `name: str`
- `APIKeyResponse` -- response: `id, name, key_prefix, created_at, last_used_at, is_active` (never includes the key itself)
- `APIKeyCreated` -- one-time response: extends `APIKeyResponse` with `key: str` (the full plaintext key, shown once)
- `APIKeyList` -- response: list of `APIKeyResponse`

#### 1.3 Create auth router

**File:** `app/api/routers/auth.py` (new)

Endpoints:
- `POST /auth/api-keys` -- Create a new API key
  - Requires an existing user_id (bootstrapping problem -- see 1.6)
  - Generates `sb_live_<32-hex>`, hashes with bcrypt, stores hash + prefix
  - Returns `APIKeyCreated` with the plaintext key (only time it's shown)
- `GET /auth/api-keys` -- List all keys for the current user (names, prefixes, last_used -- no hashes)
- `DELETE /auth/api-keys/{key_id}` -- Revoke a key (set `is_active=False`)
- `POST /auth/api-keys/{key_id}/regenerate` -- Revoke old key, create new one, return new plaintext

All auth endpoints are authenticated (chicken-and-egg resolved in 1.6).

#### 1.4 Modify `app/core/security.py` -- API key verification

**File:** `app/core/security.py` (modify)

Replace the current `get_current_user_id` function:

```
async def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> uuid.UUID:
```

Logic:
1. If `Authorization` header present and starts with `Bearer sb_`:
   - Extract the key
   - Look up keys where `key_prefix` matches the first 8 chars AND `is_active=True`
   - For matching rows, bcrypt-verify the full key against `key_hash`
   - If match found: update `last_used_at`, return `user_id`
   - If no match: raise 401
2. Elif `X-User-Id` header present AND `app_env == "development"`:
   - Use existing UUID extraction logic (backward compat for tests)
3. Else: raise 401

**Performance note:** The `key_prefix` lookup narrows candidates to 1 row (prefixes are practically unique), so we only run bcrypt.verify once. No full-table scan.

**Database session:** `get_current_user_id` currently has no DB access. It will now need a `db: AsyncSession` parameter. This changes its signature -- update `app/api/deps.py` accordingly and all routers that use it as a dependency.

#### 1.5 Update `app/api/deps.py`

**File:** `app/api/deps.py` (modify)

The `get_current_user_id` dependency needs a database session. Create a composite dependency:

```python
async def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
```

Since `get_current_user_id` is imported from `security.py` and re-exported from `deps.py`, the change flows through. No router changes needed if they already use `Depends(get_current_user_id)`.

#### 1.6 Bootstrapping: first API key creation

**Problem:** How does the user create their first API key if all endpoints require auth?

**Solution:** A CLI management command + a dev-only bootstrap endpoint:

- **CLI command:** `python -m app.cli.create_api_key --user-id <UUID> --name "initial"` -- direct DB access, no HTTP. Run this on the server after deployment.
- **Dev-only endpoint:** `POST /auth/bootstrap` (only available when `app_env=development`). Accepts `X-User-Id` and creates a key. Logs a warning.

**File:** `app/cli/__init__.py` (new, empty)
**File:** `app/cli/create_api_key.py` (new) -- standalone script that imports models, creates a session, generates a key, prints it to stdout.

#### 1.7 Alembic migration

**File:** `alembic/versions/004_add_api_keys_table.py` (new)

Migration:
- Create `api_keys` table with columns matching the model
- Index on `key_prefix` for fast lookup
- Index on `user_id` for listing a user's keys

#### 1.8 Add bcrypt dependency

**File:** `requirements.txt` (modify)

Add: `bcrypt>=4.0,<5.0`

Do NOT use `passlib` -- it adds complexity and the `bcrypt` package alone is sufficient. Use `bcrypt.hashpw()` and `bcrypt.checkpw()` directly.

#### 1.9 Register auth router

**File:** `app/main.py` (modify)

Add `from app.api.routers import auth` and `app.include_router(auth.router)`.

### Files to create (Phase 1):
| File | Purpose |
|---|---|
| `app/models/api_key.py` | APIKey SQLAlchemy model |
| `app/api/routers/auth.py` | Auth endpoints |
| `app/api/schemas/auth.py` | Auth request/response schemas |
| `app/cli/__init__.py` | Package init for management commands |
| `app/cli/create_api_key.py` | Bootstrap script for first API key |
| `alembic/versions/004_add_api_keys_table.py` | Migration |

### Files to modify (Phase 1):
| File | Change |
|---|---|
| `app/core/security.py` | API key verification with bcrypt |
| `app/api/deps.py` | Add DB session to auth dependency |
| `app/models/__init__.py` | Export APIKey |
| `app/models/user.py` | Add `api_keys` relationship |
| `app/main.py` | Register auth router |
| `requirements.txt` | Add `bcrypt` |

### Testing strategy (Phase 1):
1. **Unit tests:** `tests/unit/test_api_key_auth.py`
   - Test key generation format (`sb_live_` prefix, 40 chars)
   - Test bcrypt hash/verify roundtrip
   - Test `get_current_user_id` with valid Bearer token returns correct user_id
   - Test `get_current_user_id` with invalid token raises 401
   - Test `get_current_user_id` with revoked key raises 401
   - Test `X-User-Id` fallback works in development mode
   - Test `X-User-Id` is rejected in production mode
2. **Integration tests:** `tests/integration/test_auth_endpoints.py`
   - Create key via `POST /auth/api-keys`, verify response includes plaintext key
   - Use key to access a protected endpoint
   - Revoke key, verify subsequent requests fail
   - List keys, verify plaintext is never returned
3. **Manual on VM:** Generate a key via bootstrap script, use it with `curl -H "Authorization: Bearer sb_live_..." http://<tailscale-hostname>:8080/health` against the deployed server

---

## Phase 2: Server-Side Sync

### Goal
Move background sync from the CLI to the server so data syncs 24/7 regardless of whether any CLI is connected.

### Estimated complexity: Medium
### Dependencies: Phase 1 (new endpoints need auth)

### Tasks

#### 2.1 Create sync scheduler service

**File:** `app/services/sync/scheduler.py` (new)

Class `SyncScheduler`:
- Uses APScheduler `AsyncIOScheduler` (same pattern as `app/services/briefing/scheduler.py`)
- On startup: queries all users with active integrations, schedules sync jobs per user
- Each job calls the existing `POST /ingest/sync/{platform}` logic internally (reuse the service layer, not HTTP)
- Default interval: 30 minutes (configurable per user)
- Respects rate limits: if a sync fails with 429, exponential backoff
- Stores last sync time and status in a new `sync_status` table or JSONB column on `Integration`

**File:** `app/services/sync/__init__.py` (new, empty)

#### 2.2 Create sync status tracking

**File:** `app/models/integration.py` (modify)

Add columns to the existing `Integration` model:
- `sync_enabled: bool` (default True)
- `sync_interval_minutes: int` (default 30)
- `last_sync_at: Optional[datetime]`
- `last_sync_status: Optional[str]` (e.g., "success", "error", "rate_limited")
- `last_sync_error: Optional[str]` (error message if failed)

This keeps sync config co-located with the integration it belongs to, avoiding a new table.

#### 2.3 Create sync router

**File:** `app/api/routers/sync.py` (new)

Endpoints:
- `GET /sync/status` -- Returns sync status for all integrations (last_sync_at, next_scheduled, status)
- `POST /sync/configure` -- Update sync interval and enabled/disabled per platform
  - Body: `{ "platform": "outlook", "enabled": true, "interval_minutes": 30 }`
- `POST /sync/trigger/{platform}` -- Force an immediate sync (delegates to existing ingestion logic)
  - Different from `/ingest/sync/{platform}` in that it also updates sync tracking columns

#### 2.4 Wire scheduler into app lifespan

**File:** `app/main.py` (modify)

In the `lifespan` context manager:
- On startup (after yield setup):
  - Create `SyncScheduler` instance
  - Call `scheduler.start()` to begin periodic syncs
  - Store scheduler in `app.state.sync_scheduler`
- On shutdown:
  - Call `scheduler.shutdown()`

Only start the scheduler if `app_env == "production"` or a new setting `enable_sync_scheduler: bool = False` is True. This prevents the scheduler from running during tests or local dev (where CLI-side sync is still available).

#### 2.5 Adapt CLI background sync

**File:** `cli/background.py` (modify)

Add a check at the start of `BackgroundSync.start()`:
- Call `GET /sync/status` to check if server-side sync is active
- If server reports active sync scheduling, skip client-side sync loop and log: "Server-side sync active, skipping client-side sync"
- If server has no sync scheduling (e.g., local dev mode), run client-side sync as before

This makes the transition transparent -- the CLI auto-detects whether to sync locally or defer to the server.

#### 2.6 Alembic migration

**File:** `alembic/versions/005_add_sync_columns_to_integrations.py` (new)

Add the new columns to the `integrations` table with appropriate defaults.

### Files to create (Phase 2):
| File | Purpose |
|---|---|
| `app/services/sync/__init__.py` | Package init |
| `app/services/sync/scheduler.py` | Server-side sync scheduler |
| `app/api/routers/sync.py` | Sync management endpoints |
| `app/api/schemas/sync.py` | Sync request/response schemas |
| `alembic/versions/005_add_sync_columns_to_integrations.py` | Migration |

### Files to modify (Phase 2):
| File | Change |
|---|---|
| `app/models/integration.py` | Add sync tracking columns |
| `app/main.py` | Wire scheduler into lifespan |
| `cli/background.py` | Auto-detect server-side sync |

### Testing strategy (Phase 2):
1. **Unit tests:** `tests/unit/test_sync_scheduler.py`
   - Test scheduler starts and stops cleanly
   - Test job scheduling with correct intervals
   - Test sync status tracking (success, error states)
2. **Integration tests:** `tests/integration/test_sync_endpoints.py`
   - Configure sync via API, verify stored correctly
   - Trigger manual sync, verify status updated
   - Get sync status, verify response format
3. **Manual on VM:** Deploy, wait 30+ minutes, verify `GET /sync/status` shows successful syncs with timestamps

---

## Phase 3: Server-Side User State

### Goal
Move onboarding state, preferences, and Notion config from `~/.secondbrain/config.json` to the server so all CLI instances share the same state.

### Estimated complexity: Medium
### Dependencies: Phase 1 (auth for new endpoints), Phase 2 (sync config is already server-side)

### Tasks

#### 3.1 Extend User model with preferences

**File:** `app/models/user.py` (modify)

Add columns:
- `onboarding_completed: bool` (default False)
- `onboarding_step: int` (default 0)
- `preferences: dict` (JSONB, default `{}`) -- sync interval, notification settings, etc.
- `notion_config: Optional[dict]` (JSONB, nullable) -- Notion workspace IDs, database IDs, enabled flag

Use `sqlalchemy.dialects.postgresql.JSONB` for the dict columns.

#### 3.2 Create/extend user preferences endpoints

**File:** `app/api/routers/users.py` (modify)

Add endpoints:
- `GET /users/me/preferences` -- Return full preferences + onboarding state + notion config
- `PATCH /users/me/preferences` -- Partial update of preferences JSONB
- `GET /users/me/onboarding` -- Return `{ step, completed }`
- `PATCH /users/me/onboarding` -- Update onboarding step/completion
- `GET /users/me/notion-config` -- Return Notion workspace config
- `PUT /users/me/notion-config` -- Replace Notion config

Note: Use `/users/me` instead of `/users/{id}` since auth already identifies the user. This is more RESTful and prevents IDOR issues.

**File:** `app/api/schemas/user.py` (modify)

Add schemas:
- `UserPreferencesResponse` -- preferences dict, onboarding state
- `UserPreferencesUpdate` -- partial update
- `OnboardingState` -- step + completed
- `NotionConfigResponse` / `NotionConfigUpdate`

#### 3.3 Modify CLI config to be minimal

**File:** `cli/config.py` (modify)

`CLIConfig` becomes a thin wrapper storing only:
- `server_url: str`
- `api_key: Optional[str]` (added in Phase 5 for login, but prepare the field now)
- `user_id: Optional[str]` (cached from server for offline reference)
- `user_name: Optional[str]` (cached)
- `user_email: Optional[str]` (cached)

All other fields (`onboarding_completed`, `onboarding_step`, `platforms_connected`, `identity_configured`, `initial_import_done`, `preferences`, `notion`) are removed from local config and fetched from server on demand.

Add a `is_remote_mode` property: returns True if `server_url` is not localhost.

For backward compatibility, the `load()` method should still parse old config files without crashing (ignore unknown fields silently).

#### 3.4 Modify CLI onboarding to use server state

**File:** `cli/onboarding.py` (modify)

Replace all reads/writes of `config.onboarding_step` and `config.onboarding_completed` with API calls:
- On start: `GET /users/me/onboarding` to determine current step
- After each step: `PATCH /users/me/onboarding` to persist progress
- This makes onboarding resumable across devices

#### 3.5 Modify CLI commands to fetch from server

**File:** `cli/commands.py` (modify)

For Notion-related commands (`/notion-sync`, `/notion-briefing`, etc.):
- Fetch Notion config from `GET /users/me/notion-config` instead of `config.notion`
- After config changes, `PUT /users/me/notion-config` instead of `config.save()`

#### 3.6 Alembic migration

**File:** `alembic/versions/006_add_user_preferences_columns.py` (new)

Add `onboarding_completed`, `onboarding_step`, `preferences`, `notion_config` columns to `users` table.

### Files to create (Phase 3):
| File | Purpose |
|---|---|
| `alembic/versions/006_add_user_preferences_columns.py` | Migration |

### Files to modify (Phase 3):
| File | Change |
|---|---|
| `app/models/user.py` | Add preferences/onboarding/notion columns |
| `app/api/routers/users.py` | Preferences endpoints |
| `app/api/schemas/user.py` | New schemas |
| `cli/config.py` | Slim down to minimal fields |
| `cli/onboarding.py` | API-backed state |
| `cli/commands.py` | Server-side Notion config |
| `cli/api_client.py` | Add preferences/onboarding API methods |

### Testing strategy (Phase 3):
1. **Unit tests:** `tests/unit/test_user_preferences.py`
   - Test JSONB serialization/deserialization of preferences
   - Test onboarding state transitions
2. **Integration tests:** `tests/integration/test_preferences_endpoints.py`
   - Set preferences via API, verify persisted
   - Update onboarding step, verify state across requests
   - Set Notion config, verify retrieval
3. **CLI tests:** Verify onboarding works in remote mode (mock API calls)
4. **Manual:** Start onboarding on one machine, resume on another

---

## Phase 5: CLI Packaging and Login Flow

### Goal
Package the CLI as an installable pip package with a `secondbrain login` flow so any machine can connect in under a minute.

### Estimated complexity: Medium
### Dependencies: Phase 1 (API keys exist), Phase 3 (minimal local config), Phase 4 (deployed server)

### Tasks

#### 5.1 Create CLI package configuration

**File:** `pyproject.toml` (new, project root -- or `cli/pyproject.toml` if we want the CLI as a separate package)

**Decision:** Single `pyproject.toml` at the project root. The CLI is part of the same repo but packaged separately. Use a `[project.scripts]` entry point:

```toml
[project]
name = "secondbrain-cli"
version = "0.1.0"
description = "secondBrain CLI — Your AI Chief of Staff"
requires-python = ">=3.8"
dependencies = [
    "httpx>=0.27",
    "rich>=13.0",
    "prompt-toolkit>=3.0",
]

[project.scripts]
secondbrain = "cli.main:main"
```

**Note:** The CLI package only depends on `httpx`, `rich`, `prompt-toolkit` -- NOT on FastAPI, SQLAlchemy, or any backend deps. This keeps the install lightweight.

#### 5.2 Add `login` and `logout` commands

**File:** `cli/main.py` (modify)

Add new subcommands to `argparse`:
- `secondbrain login` -- Interactive login flow
- `secondbrain logout` -- Clear local credentials
- `secondbrain chat` -- Existing chat mode (default if no subcommand and already logged in)
- `secondbrain install` -- Existing local install (kept for local dev)

**File:** `cli/auth.py` (new)

Login flow:
1. Prompt for server URL (default: `http://<tailscale-hostname>:8080`)
2. Prompt for API key (masked input, like a password)
3. Validate by calling `GET /health` with the key in `Authorization: Bearer` header
4. If valid: store `server_url` and `api_key` in `~/.secondbrain/config.json`
5. Fetch user info via `GET /users/me` and cache `user_id`, `user_name`, `user_email`
6. Print success message with user name

Logout flow:
1. Clear `api_key`, `user_id`, `user_name`, `user_email` from config
2. Keep `server_url` (user might want to re-login)
3. Print confirmation

#### 5.3 Modify `APIClient` to support Bearer auth

**File:** `cli/api_client.py` (modify)

Update `__init__` to accept an optional `api_key: str` parameter.

Update `_headers()`:
- If `api_key` is set: `{"Authorization": f"Bearer {api_key}"}`
- Elif `user_id` is set (legacy local mode): `{"X-User-Id": user_id}`
- Else: no auth headers

This makes the API client work in both modes during the transition.

#### 5.4 Modify `cli/main.py` -- remote mode

**File:** `cli/main.py` (modify)

In `async_main`:
- If `config.api_key` is set, create `APIClient` with `api_key` instead of `user_id`
- If `config.is_remote_mode` (server_url is not localhost):
  - Skip all `ServerManager` logic (don't try to start local Docker/server)
  - Skip `cli install` prompts
  - If not logged in (`api_key` is None), prompt to run `secondbrain login`

#### 5.5 Modify `cli/server.py` -- conditional local mode

**File:** `cli/server.py` (modify)

Add a guard at the top of `ServerManager.__init__`:
- If `config.is_remote_mode`, all methods become no-ops (or raise a clear error)
- This prevents accidental Docker management when pointing to a remote server

#### 5.6 Update `install.sh` -- add remote flag

**File:** `install.sh` (modify)

Add `--remote` flag:
- `./install.sh --remote` skips Docker, DB, and server setup
- Instead: `pip install .` (installs the CLI package from pyproject.toml)
- Runs `secondbrain login` interactively
- Print instructions for adding the `secondbrain` command to PATH if needed

#### 5.7 Config file security

**File:** `cli/config.py` (modify)

Since `config.json` now stores an API key:
- Ensure `chmod 0o600` on save (already done, verify)
- Add a warning on load if permissions are too open (readable by group/others)
- Consider: on macOS, store the API key in Keychain instead of plaintext JSON (future improvement, out of scope for now but document as a TODO)

### Files to create (Phase 5):
| File | Purpose |
|---|---|
| `pyproject.toml` | CLI package config |
| `cli/auth.py` | Login/logout flow |

### Files to modify (Phase 5):
| File | Change |
|---|---|
| `cli/main.py` | Add login/logout subcommands, remote mode |
| `cli/api_client.py` | Support Bearer auth |
| `cli/config.py` | Add `api_key` field, `is_remote_mode` |
| `cli/server.py` | Guard against remote mode |
| `install.sh` | Add `--remote` flag |

### Testing strategy (Phase 5):
1. **Unit tests:** `tests/unit/test_cli_auth.py`
   - Test login flow stores credentials correctly
   - Test logout clears credentials
   - Test `APIClient` sends correct auth header based on mode
   - Test `is_remote_mode` detection
2. **Integration test:** From a clean machine (or clean virtualenv):
   - `pip install .`
   - `secondbrain login` with the deployed server URL and API key
   - `secondbrain` starts chat successfully
3. **Manual:** Test on a second machine (or VM) with only pip installed -- no source code checkout

---

## Data Migration Path

After all phases are implemented:

1. **Export local data:**
   ```bash
   docker exec secondbrain-db pg_dump -U secondbrain secondbrain > local-backup.sql
   ```

2. **Import to production DB:**
   ```bash
   # Copy to VM via Tailscale
   scp local-backup.sql <tailscale-hostname>:/tmp/
   # Import (the prod DB container)
   ssh <tailscale-hostname>
   docker exec -i secondbrain-db-prod psql -U secondbrain secondbrain < /tmp/local-backup.sql
   ```

3. **Fernet key:** Copy the same `FERNET_KEY` from local `.env` to `.env.prod`. If you change it, all encrypted platform tokens become unreadable and integrations must be re-connected.

4. **Generate API key:**
   ```bash
   ssh <tailscale-hostname>
   cd /opt/secondbrain
   docker exec -it secondbrain-api python -m app.cli.create_api_key --user-id <UUID> --name "initial"
   ```

5. **Login from any device:**
   ```bash
   pip install secondbrain-cli
   secondbrain login
   # Enter server URL and API key
   ```

---

## Risks and Considerations

| Risk | Severity | Mitigation |
|---|---|---|
| **Oracle Cloud free tier limits** | Low | ARM A1 gets 4 OCPU + 24GB RAM for free; our usage is well under. Monitor with `docker stats`. Oracle may change free tier terms -- keep backups portable. |
| **API key in plaintext config** | Low | `chmod 600` on config file. Server only accessible via Tailscale, reducing exposure. Future: macOS Keychain integration. |
| **ARM compatibility** | Low | All Docker images used (`python:3.11-slim`, `pgvector/pgvector:pg16`) have official `linux/arm64` builds. Test locally on Apple Silicon Mac (same arch). |
| **GHCR availability** | Low | GitHub has 99.9%+ uptime. If GHCR is down, the VM keeps running the last pulled image. Can fallback to local `docker build` if needed. |
| **Tailscale dependency** | Low | If Tailscale goes down, server is unreachable. Fallback: direct SSH via Oracle Cloud console. Tailscale has excellent uptime and the mesh is self-healing. |
| **VM goes down** | Medium | Systemd auto-restarts Docker Compose on reboot. For longer outages: Oracle Cloud has 99.9% SLA on free tier compute. Backups run daily to local disk; consider offsite backup to OCI Object Storage (free tier: 10GB). |
| **Database on same VM** | Medium | Single point of failure. Acceptable for personal use. Daily `pg_dump` backups mitigate data loss. Future: migrate to Supabase or separate DB instance if needed. |
| **Breaking change to `get_current_user_id` signature** | Low | Adding `db` parameter changes the FastAPI dependency. Since all routers already use `Depends(get_current_user_id)`, FastAPI resolves the sub-dependencies automatically. Test all routers after the change. |
| **Sync scheduler competing with CLI sync** | Low | Phase 2 adds auto-detection: CLI checks if server-side sync is active and defers. Syncs are idempotent (upsert by source_id), so double-syncing is harmless, just wasteful. |

---

## Monitoring and Alerting

Lightweight monitoring appropriate for a single-user personal tool:

1. **Health check endpoint** (`/health/detailed`) — already planned in Phase 4
2. **Uptime monitoring** — Since the server is on Tailscale (not public), use a cron on a tailnet device to ping `http://<tailscale-hostname>:8080/health`. Or use Healthchecks.io with a push model (the server pings out).
3. **Docker logs** — `docker compose -f docker-compose.prod.yml logs -f` for live debugging
4. **Disk space** — Add to `infra/backup.sh`: warn if disk usage > 80%
5. **Sync health** — The `GET /sync/status` endpoint shows if syncs are failing. Future: add a "sync has not run in 2 hours" alert to the briefing.

---

## Complete File Inventory

### Files to create (all phases):

| File | Phase | Purpose |
|---|---|---|
| `Dockerfile` | 4 | API server container |
| `docker-compose.prod.yml` | 4 | Production stack (db + api from GHCR) |
| `.github/workflows/build-and-push.yml` | 4 | CI: build + push to GHCR |
| `infra/nginx/secondbrain.conf` | 4 | Nginx server block (HTTP reverse proxy) |
| `infra/docker-entrypoint.sh` | 4 | Migration + startup |
| `infra/deploy.sh` | 4 | Pull + restart (via Tailscale SSH) |
| `infra/backup.sh` | 4 | PostgreSQL backup |
| `infra/secondbrain.service` | 4 | Systemd unit |
| `.env.prod.example` | 4 | Env var template |
| `app/models/api_key.py` | 1 | APIKey model |
| `app/api/routers/auth.py` | 1 | Auth endpoints |
| `app/api/schemas/auth.py` | 1 | Auth schemas |
| `app/cli/__init__.py` | 1 | Management commands package |
| `app/cli/create_api_key.py` | 1 | Bootstrap script |
| `alembic/versions/004_add_api_keys_table.py` | 1 | Migration |
| `app/services/sync/__init__.py` | 2 | Package init |
| `app/services/sync/scheduler.py` | 2 | Sync scheduler |
| `app/api/routers/sync.py` | 2 | Sync endpoints |
| `app/api/schemas/sync.py` | 2 | Sync schemas |
| `alembic/versions/005_add_sync_columns_to_integrations.py` | 2 | Migration |
| `alembic/versions/006_add_user_preferences_columns.py` | 3 | Migration |
| `pyproject.toml` | 5 | CLI package config |
| `cli/auth.py` | 5 | Login/logout flow |

### Files to modify (all phases):

| File | Phases | Changes |
|---|---|---|
| `app/main.py` | 4, 1, 2 | CORS, auth router, sync scheduler in lifespan |
| `app/core/config.py` | 4 | Production settings |
| `app/core/security.py` | 1 | API key verification |
| `app/api/deps.py` | 1 | DB session in auth dependency |
| `app/api/routers/health.py` | 4 | Enhanced health check |
| `app/api/routers/users.py` | 3 | Preferences endpoints |
| `app/api/schemas/user.py` | 3 | Preferences schemas |
| `app/models/__init__.py` | 1 | Export APIKey |
| `app/models/user.py` | 1, 3 | api_keys relationship, preferences columns |
| `app/models/integration.py` | 2 | Sync tracking columns |
| `cli/main.py` | 5 | Login/logout subcommands, remote mode |
| `cli/config.py` | 3, 5 | Slim down, add api_key field |
| `cli/api_client.py` | 3, 5 | Preferences methods, Bearer auth |
| `cli/background.py` | 2 | Auto-detect server-side sync |
| `cli/onboarding.py` | 3 | API-backed state |
| `cli/commands.py` | 3 | Server-side Notion config |
| `cli/server.py` | 5 | Guard against remote mode |
| `requirements.txt` | 1 | Add bcrypt |
| `.gitignore` | 4 | Add .env.prod, backups/ |
| `install.sh` | 5 | Add --remote flag |

---

## Effort Estimate

| Phase | Complexity | Estimated Effort |
|---|---|---|
| Phase 0: VM Provisioning | Low | 1-2 hours (manual) |
| Phase 4: Containerization + Deploy | Medium | 2-3 days |
| Phase 1: Authentication | Medium | 2-3 days |
| Phase 2: Server-Side Sync | Medium | 2-3 days |
| Phase 3: Server-Side State | Medium | 2-3 days |
| Phase 5: CLI Packaging + Login | Medium | 2-3 days |
| **Total** | | **10-15 days** |

Code review between each phase per established workflow.
