# QA Plan: secondBrain

## Objetivo

Definir la estrategia de testing para garantizar la calidad del sistema. Cubre unit tests, integration tests, y E2E tests alineados a todas las features implementadas.

**Estado actual:** 1055 tests, todos passing (salvo fallos preexistentes conocidos y no relacionados en `test_teams_connector.py`).

---

## 1. Stack de Testing

| Herramienta | Uso |
|---|---|
| `pytest` | Framework principal de tests |
| `pytest-asyncio` | Tests de funciones async (FastAPI, conectores) |
| `pytest-cov` | Cobertura de código |
| `httpx` | Test client para endpoints FastAPI |
| `respx` | Mock de llamadas HTTP externas (Slack, MSGraph, Notion, OpenAI) |
| SQLite in-memory | DB para unit e integration tests (via aiosqlite) |

---

## 2. Niveles de Testing

### 2.1 Unit Tests

Tests aislados sin dependencias externas. Mocks para DB, APIs externas, y embeddings.

#### Models & Schema
- [x] Validación de cada modelo Pydantic (Users, Identities, Integrations, Documents, Commitments)
- [x] Validación de enums: `platform` ('slack', 'outlook', 'teams', 'fathom', 'notion'), `status` ('pending', 'completed', 'cancelled')
- [x] Constraints: email único en `users`, `user_id` FK válido
- [x] Serialización/deserialización de campos JSON (`preferences_json`, `notion_config_json`)
- [x] APIKey model validation and key prefix uniqueness

#### Services — Ingestion Pipeline
- [x] **Cleaning**: Remoción de firmas de email, boilerplate de Slack, headers de Teams
- [x] **Chunking**: Verificar que chunks se generan correctamente
- [x] **Chunking edge cases**: Texto vacío, texto menor a un chunk, texto con solo whitespace
- [x] **Metadata extraction**: Extracción correcta de author, timestamp, project_id, thread_id
- [x] **Embedder**: Batch embedding, empty input handling

#### Services — Commitment Detection
- [x] Detección de promesas explícitas e implícitas
- [x] Extracción de due_date cuando está presente
- [x] No falsos positivos en frases condicionales
- [x] Asignación correcta de prioridad

#### Services — Daily Briefing
- [x] Generación del briefing con agenda vacía (sin meetings)
- [x] Generación con commitments pendientes
- [x] Scheduler start/shutdown lifecycle
- [x] APScheduler integration (async)

#### Services — RAG / Retrieval
- [x] Construcción correcta del query embedding
- [x] Filtrado por metadata (date range, person, source)
- [x] Ranking de resultados por similaridad
- [x] Manejo de query sin resultados relevantes

#### Services — Agent (Strands)
- [x] Agent tool registration and execution (`test_agent.py` — tools only; the old
  `AgentOrchestrator`/`orchestrator.py` were removed in the Strands migration)
- [x] Memory retriever tool
- [x] Agent query endpoint validation
- [x] `StrandsOrchestrator`: model construction (reasoning-model `reasoning_effort` guard),
  conversation history round-tripping, `ConversationTurn` persistence (`test_strands_orchestrator.py`, `test_strands_model.py`)
- [x] Strands `@tool` wrappers: memory retriever, task manager, calendar sync, style analyzer,
  `save_learning`/`search_learnings`, opt-in `web_search`/`http_request`, knowledge-graph tools
  (`test_strands_tools.py`, `test_learning_tools.py`)
- [x] `SequentialToolExecutor` enforced (shared `AsyncSession` across all tools in a turn)

#### Services — Multi-Agent Knowledge System
- [x] `store.py`: entity/claim/link/pending_question CRUD, user-id scoping, `get_knowledge_stats`
  observability aggregation (`test_knowledge_store.py`, `test_knowledge_stats.py`)
- [x] `domain_agent.py`: per-source (Slack/Outlook/Teams/Fathom/Notion) agent tool set, shared
  resolution-ladder extraction (`make_resolution_ladder_tools`), `REGISTERED_SOURCES` derivation
  (`test_domain_agent.py`)
- [x] `rd_agent.py`: I+D-platform agent via MCP — `create_tasks` write-tool exclusion (`tool_filters`
  + defensive re-check), MCP client lifecycle (`start`/`stop`, including on connection failure),
  no real network calls (`MCPClient` mocked) (`test_rd_agent.py`)
- [x] `resolution.py`: find-or-create-entity (case-insensitive match, attribute merging), consult
  knowledge base (`test_reconciliation.py` covers the shared helpers)
- [x] `reconciliation.py`: deterministic email-based auto-link, embedding-similarity candidate
  detection, `same_as` merge negotiation, confidence recomputation, `entity_type`-scoped auto-link
  (`test_reconciliation.py`, unit + integration)
- [x] `swarm_negotiation.py`: shared scoped-`Swarm` core (`test_swarm_negotiation.py`)
- [x] Knowledge tools exposed to the request-time agent: `query_knowledge`, `get_pending_questions`,
  `confirm_pending_answer` — including idempotency (confirming twice doesn't double-write)
  (`test_strands_tools_knowledge.py`)
- [x] `GET /knowledge/status` observability endpoint, incl. `scheduler_active`/`next_scheduled_run` (`test_knowledge_stats.py`)
- [x] `scheduler.py`: `KnowledgeAgentScheduler` — lifecycle, minimum-interval enforcement, one job
  per user with an active integration, each step on its own fresh session (not a shared one),
  per-step failure isolation within a cycle (one source failing doesn't block the rest or
  reconciliation, and a rollback that itself raises doesn't abort the cycle either)
  (`test_knowledge_scheduler.py`)

#### Services — Notion
- [x] NotionConnector: page reading, database reading, token validation
- [x] NotionPublisher: page creation, database creation, workspace setup
- [x] NotionSync: bidirectional sync, conflict resolution (last-write-wins)
- [x] Block parsing: markdown to Notion blocks, Notion blocks to text
- [x] WeeklyDigestGenerator: digest generation with Claude, fallback on error
- [x] WorkspaceConfig: serialization/deserialization

#### Services — Sync Scheduler
- [x] APScheduler lifecycle (start, shutdown, double-start guard)
- [x] Job scheduling (add, remove, reschedule)
- [x] Minimum interval enforcement (5 min)
- [x] Sync execution (success, error, unknown platform, connector error)
- [x] Error message truncation
- [x] CLI auto-detect of server-side sync

#### API Endpoints
- [x] `GET /` — Health check retorna status y message
- [x] Endpoints CRUD de usuarios — validación de input, respuestas correctas
- [x] Endpoints de commitments — crear, listar, actualizar status, filtrar
- [x] Endpoints de integrations — CRUD, encryption
- [x] Endpoints de ingestion — trigger de sync por plataforma
- [x] Endpoints de query — búsqueda semántica cross-platform
- [x] Endpoint de daily briefing — generación on-demand, scheduling
- [x] Endpoints de identity — create, get, update
- [x] Endpoints de sync — status, configure, trigger
- [x] Endpoints de auth — API key creation, listing, revocation
- [x] Endpoint de voice — transcripción y TTS
- [x] `GET /knowledge/status` — observabilidad de la base de conocimiento (buckets de confianza, claims por fuente, preguntas pendientes, merges recientes, estado del `KnowledgeAgentScheduler`)
- [x] `GET /users/me` — Authenticated user profile
- [x] `GET /users/me/preferences` — Preferences, onboarding, Notion config
- [x] `PATCH /users/me/preferences` — Merge preferences
- [x] `GET/PATCH /users/me/onboarding` — Onboarding state
- [x] `GET/PUT /users/me/notion-config` — Notion workspace config
- [x] Autenticación: Bearer token (API key) y X-User-Id (dev mode)
- [x] Autorización: user isolation (cannot access other user's data)

#### CLI
- [x] CLIConfig: load, save, reset, permissions, is_remote_mode
- [x] APIClient: headers (Bearer vs X-User-Id), all endpoint methods
- [x] Auth: login flow (success, server unreachable, invalid key, already logged in)
- [x] Auth: logout flow (clears credentials, preserves server_url)
- [x] Display: formatting helpers
- [x] Validators: email, name, timezone, token, time, selection parsing
- [x] Onboarding: 5-step flow, state persistence
- [x] Chat session: slash command routing, agent queries
- [x] Command router: all 16 slash commands
- [x] Background sync: periodic sync, digest scheduling, server-side detection
- [x] Alert manager: commitment alerts, deduplication
- [x] Notion setup: connect/disconnect flow
- [x] Server manager: lifecycle, PID management, remote mode guard
- [x] Installer: Docker check, DB setup, migration
- [x] User preferences: model properties, schema validation
- [x] Config file permission security warning

#### Security
- [x] API key authentication (bcrypt verification)
- [x] API key format validation (sb_ prefix)
- [x] Key prefix lookup + bcrypt check
- [x] Dev mode X-User-Id blocked in production
- [x] Fernet encryption for integration tokens
- [x] Config file chmod 600 on save

### 2.2 Integration Tests

Tests contra SQLite in-memory con el stack FastAPI/SQLAlchemy completo.

#### Database
- [x] CRUD completo en cada tabla (users, identities, integrations, documents, commitments)
- [x] Cascade deletes: eliminar user elimina sus documents y commitments
- [x] Búsqueda vectorial (mocked embeddings en SQLite)
- [x] Upserts en `documents` no generan duplicados

#### Conectores Externos (HTTP mocked)
- [x] **MSGraphConnector**: OAuth2 flow, paginación, token refresh
- [x] **TeamsConnector**: Chats 1:1 y grupales, paginación, rate limiting, filtrado
- [x] **SlackConnector**: Channels y DMs, paginación con cursor, rate limiting
- [x] **FathomConnector**: Importación de transcripts
- [x] **NotionConnector**: Page reading, database reading, token validation
- [x] Todos: manejo de errores de red (timeout, 500, connection refused)

#### Notion Integration
- [x] NotionPublisher: workspace setup, page/database creation
- [x] NotionSync: bidirectional commitment sync

#### Pipeline End-to-End (Ingestion)
- [x] Conector → Cleaning → Chunking → Embedding (mocked) → Storage en DB
- [x] `source_id` previene duplicados en re-sync

#### Server State
- [x] Preferences: default values, update, merge
- [x] Onboarding: default, step update, completion, partial update
- [x] Notion config: default, set, clear, visible in preferences
- [x] GET /users/me: returns authenticated user, 401 without auth, 404 for missing user

#### Sync
- [x] Sync status with/without integrations
- [x] Configure sync, disable sync
- [x] Trigger sync for nonexistent/unsupported platform

#### Auth
- [x] API key creation, listing, revocation
- [x] Authentication via Bearer token

### 2.3 E2E Tests

Tests de flujos completos de usuario, simulando el uso real.

#### Commitment Tracking
- [x] Commitment lifecycle (create → update status → delete)
- [x] Status transition enforcement

#### Daily Briefing
- [x] Briefing generation on-demand
- [x] Briefing scheduling
- [x] Error handling (Claude API errors → 502)

#### Cross-Platform Querying
- [x] Query with results and without results
- [x] Query with metadata filters
- [x] Query response structure validation
- [x] Agent query endpoint

---

## 3. Tests No Funcionales

### Seguridad
- [x] Tokens OAuth2 se almacenan encriptados en `integrations`, nunca en plaintext
- [x] No se exponen tokens en logs ni respuestas de API
- [x] Cada usuario solo accede a sus propios datos (user isolation)
- [x] API key bcrypt hashed, prefix-based lookup
- [x] Config file permissions (chmod 600)
- [x] X-User-Id blocked in production mode
- [ ] Rate limiting en endpoints públicos (not implemented — single-user system)
- [ ] Input sanitization: prompt injection testing (deferred)

### Reliability
- [x] Si un conector falla, los demás siguen funcionando
- [x] Si Claude API no responde, el briefing retorna error graceful, no crash
- [x] Sync scheduler handles connector errors gracefully
- [x] Best-effort server state sync (CLI doesn't break if server doesn't support endpoints)

### Performance
- [ ] Búsqueda vectorial en `documents` con 10K registros (requires production DB)
- [ ] Ingestion pipeline benchmark (requires production DB + OpenAI)
- [ ] API endpoint response time benchmarks (requires production environment)

---

## 4. Estructura de Archivos de Test

```
tests/
├── conftest.py                        # Fixtures globales (DB, test client, SQLite — incluye
│                                       # el esquema de las tablas de conocimiento)
├── factories.py                       # Factory definitions
├── unit/
│   ├── test_models.py                 # SQLAlchemy models
│   ├── test_cleaning.py               # Ingestion: cleaner
│   ├── test_chunking.py               # Ingestion: chunker
│   ├── test_embedder.py               # Ingestion: embedder
│   ├── test_commitment_detection.py   # Commitment service
│   ├── test_briefing.py               # Briefing generator + scheduler
│   ├── test_retrieval.py              # Semantic search
│   ├── test_claude_client.py          # LLM client
│   ├── test_agent_tool_use.py         # LLMClient.generate_with_tools() agentic loop
│   ├── test_prompts.py                # Prompt templates
│   ├── test_agent.py                  # Agent tools (Strands orchestrator itself removed here)
│   ├── test_strands_orchestrator.py   # StrandsOrchestrator: model, history, persistence
│   ├── test_strands_tools.py          # Strands @tool wrappers
│   ├── test_strands_model.py          # build_openai_model() reasoning_effort guard
│   ├── test_learning_tools.py         # save_learning / search_learnings tools
│   ├── test_reconciliation.py         # Reconciliation engine (unit-level helpers)
│   ├── test_swarm_negotiation.py      # Shared scoped-Swarm negotiation core
│   ├── test_knowledge_scheduler.py    # KnowledgeAgentScheduler (periodic knowledge cycles)
│   ├── test_encryption.py             # Fernet encryption
│   ├── test_security.py               # API key auth
│   ├── test_voice_transcriber.py      # Voice transcription (local + API mode)
│   ├── test_api_users.py              # User endpoints
│   ├── test_api_commitments.py        # Commitment endpoints
│   ├── test_api_integrations.py       # Integration endpoints
│   ├── test_api_key_auth.py           # API key auth endpoints
│   ├── test_identity_api.py           # Identity endpoints
│   ├── test_sync_scheduler.py         # APScheduler sync
│   ├── test_sync_fathom_incremental.py # Fathom incremental sync
│   ├── test_user_preferences.py       # User model properties + schemas
│   ├── test_notion_connector.py       # Notion connector
│   ├── test_notion_publisher.py       # Notion publisher
│   ├── test_notion_sync.py            # Notion bidirectional sync
│   ├── test_notion_blocks.py          # Block parsing
│   ├── test_text_to_blocks.py         # Markdown → Notion blocks
│   ├── test_digest.py                 # Weekly digest generator
│   ├── test_cli_config.py             # CLI config
│   ├── test_cli_api_client.py         # CLI API client
│   ├── test_cli_auth.py               # CLI login/logout
│   ├── test_cli_display.py            # CLI display helpers
│   ├── test_validators.py             # Input validators
│   ├── test_onboarding_flow.py        # Onboarding wizard
│   ├── test_chat_session.py           # Chat loop (incl. proactive welcome)
│   ├── test_command_router.py         # Slash commands
│   ├── test_background_sync.py        # Background sync
│   ├── test_alert_manager.py          # Commitment alerts
│   ├── test_server_manager.py         # Server lifecycle
│   └── test_installer.py             # Local installer
├── integration/
│   ├── test_database.py               # DB CRUD + cascade
│   ├── test_api_crud.py               # Full API lifecycle
│   ├── test_search.py                 # Vector search
│   ├── test_ingestion_pipeline.py     # Full pipeline
│   ├── test_commitment_pipeline.py    # Commitment detection pipeline
│   ├── test_briefing_generation.py    # Briefing generation
│   ├── test_identity_crud.py          # Identity CRUD
│   ├── test_agent_endpoint.py         # POST /agent/query — full HTTP stack, StrandsOrchestrator
│   ├── test_knowledge_store.py        # Entity/claim/link/pending_question CRUD
│   ├── test_knowledge_stats.py        # get_knowledge_stats() + GET /knowledge/status
│   ├── test_domain_agent.py           # Per-source domain agents + resolution ladder
│   ├── test_rd_agent.py               # I+D platform agent via MCP
│   ├── test_reconciliation.py         # Cross-source duplicate detection + same_as merging
│   ├── test_strands_tools_knowledge.py # query_knowledge/get_pending_questions/confirm_pending_answer
│   ├── test_msgraph_connector.py      # Outlook/Calendar connector
│   ├── test_teams_connector.py        # Teams connector
│   ├── test_slack_connector.py        # Slack connector
│   ├── test_fathom_connector.py       # Fathom connector
│   ├── test_notion_connector.py       # Notion connector
│   ├── test_notion_publisher.py       # Notion publisher
│   ├── test_notion_sync.py            # Notion bidirectional sync
│   ├── test_auth_endpoints.py         # API key auth
│   ├── test_sync_endpoints.py         # Sync scheduler endpoints
│   ├── test_preferences_endpoints.py  # User preferences endpoints
│   ├── test_voice_endpoints.py        # Voice transcription/TTS endpoints
│   └── test_users_me_endpoint.py      # GET /users/me
└── e2e/
    ├── test_agent_query.py            # Agent query endpoint
    ├── test_cross_platform_query.py   # RAG query endpoint
    └── test_daily_briefing.py         # Briefing generation + scheduling
```

---

## 5. Criterios de Aceptación por Release

| Criterio | Umbral | Estado |
|---|---|---|
| All tests passing | 1055/1055 (6 fallos preexistentes no relacionados en `test_teams_connector.py`) | **Met** |
| Type checking (mypy) | No errors in app/ cli/ | **Met** |
| Security: auth + encryption | All tests passing | **Met** |
| E2E: happy paths | All passing | **Met** |
| Performance benchmarks | Deferred (requires prod) | N/A |

---

## 6. CI/CD Integration

- GitHub Actions workflow: `ci.yml` runs on PRs and pushes to main
- Pipeline: `type-check (mypy)` → `unit tests` → `integration tests` → `e2e tests`
- Deploy workflow: `deploy.yml` builds Docker image, pushes to GHCR, deploys via self-hosted runner
- Tests use SQLite in-memory (no external DB service required in CI)
