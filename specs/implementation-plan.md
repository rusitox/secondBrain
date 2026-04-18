# Plan de Implementación: secondBrain MVP

## Contexto

El proyecto secondBrain (AI Chief of Staff / Digital Twin) tiene todas las specs completas pero zero implementación — solo un health check en `app/main.py`. El objetivo es implementar el MVP en 6 fases incrementales, donde cada fase produce un entregable testeable que se apoya en la anterior.

## Grafo de Dependencias

```
Phase 1 (Foundation)
  │
Phase 2 (CRUD API)
  │
Phase 3 (Ingestion Pipeline)
  │
  ├──→ Phase 4 (RAG / Querying)        ── MVP Feature 3
  │
  ├──→ Phase 5 (Commitment Detection)   ── MVP Feature 1
  │         │
  └─────────┘
            │
      Phase 6 (Briefing + Agent)        ── MVP Feature 2
```

> Fases 4 y 5 son independientes entre sí (se pueden paralelizar). Fase 6 depende de ambas.

---

## Phase 1: Foundation — Config, DB Models, Test Infrastructure

**Objetivo**: Skeleton funcional con config, DB, modelos SQLAlchemy, migraciones, y harness de tests.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Core | `app/__init__.py`, `app/core/__init__.py`, `app/core/config.py` (Settings con pydantic-settings), `app/core/database.py` (async engine + session + pgvector), `app/core/logging.py` (structured logging) |
| Models | `app/models/__init__.py`, `app/models/base.py` (Base + UUIDMixin + TimestampMixin), `app/models/user.py`, `app/models/identity.py`, `app/models/integration.py`, `app/models/document.py` (Vector(1536) + HNSW index), `app/models/commitment.py` |
| Schemas | `app/api/__init__.py`, `app/api/schemas/__init__.py`, `app/api/schemas/user.py`, `app/api/schemas/commitment.py`, `app/api/schemas/document.py`, `app/api/schemas/integration.py` |
| Migrations | `alembic.ini`, `alembic/env.py`, `alembic/versions/001_initial_schema.py` |
| Tests | `pytest.ini`, `tests/__init__.py`, `tests/conftest.py` (async client, test DB, override deps), `tests/factories.py`, `tests/unit/__init__.py`, `tests/unit/test_models.py`, `tests/integration/__init__.py`, `tests/integration/test_database.py` |

**Modificar:** `app/main.py` (lifespan + logging), `requirements.txt` (agregar alembic, asyncpg, sqlalchemy[asyncio], structlog, pytest, pytest-asyncio, pytest-cov, httpx, factory-boy, respx, testcontainers)

**Decisiones clave:**
- `asyncpg` como driver async; `psycopg2-binary` solo para Alembic sync
- Encriptación de tokens con `cryptography.fernet` + `FERNET_KEY` en .env
- HNSW index en `documents.embedding`

**Verificación:** `pytest tests/unit/test_models.py` + `pytest tests/integration/test_database.py` + `alembic upgrade head` + health check funciona

---

## Phase 2: CRUD API y User Management

**Objetivo**: Endpoints REST para todas las entidades, scaffolding de auth, patrón de routers.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Routers | `app/api/routers/__init__.py`, `app/api/routers/users.py` (CRUD), `app/api/routers/commitments.py` (CRUD + filtros), `app/api/routers/integrations.py` (CRUD + toggle), `app/api/routers/health.py` |
| Services | `app/services/__init__.py`, `app/services/user_service.py`, `app/services/commitment_service.py`, `app/services/integration_service.py` |
| Security | `app/core/security.py` (Fernet helpers + `get_current_user` placeholder con `X-User-Id` header), `app/api/deps.py` |
| Tests | `tests/unit/test_api_users.py`, `tests/unit/test_api_commitments.py`, `tests/unit/test_api_integrations.py`, `tests/unit/test_security.py`, `tests/integration/test_api_crud.py` |

**Modificar:** `app/main.py` (registrar routers)

**Decisiones clave:**
- Row-level isolation por `user_id` desde el día 1 (vía `get_current_user` dependency)
- Tokens nunca se retornan en plaintext en responses de API
- Status transitions validadas: `pending` → `completed`/`cancelled` (sin retroceso)

**Verificación:** Tests pass + Swagger UI funcional en `/docs`

---

## Phase 3: Ingestion Pipeline — Connectors, Cleaning, Chunking, Embedding

**Objetivo**: Pipeline completo de ingesta: texto crudo → documento con embedding en DB. Cuatro conectores (MSGraph, Teams, Slack, Fathom).

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Pipeline | `app/services/ingestion/__init__.py`, `app/services/ingestion/cleaner.py` (limpieza por source), `app/services/ingestion/chunker.py` (RecursiveCharacterTextSplitter, 800 chars, 100 overlap), `app/services/ingestion/embedder.py` (OpenAI batch + retry), `app/services/ingestion/pipeline.py` (orquestador: clean→chunk→embed→upsert) |
| Connectors | `app/services/connectors/__init__.py`, `app/services/connectors/base.py` (ABC), `app/services/connectors/msgraph.py` (OAuth2, emails, calendar), `app/services/connectors/teams.py` (MS Graph, chats 1:1 y grupales, rate limiting), `app/services/connectors/slack.py` (Bot token, cursor pagination, rate limiting), `app/services/connectors/fathom.py` (API/export) |
| API | `app/api/routers/ingestion.py` (`POST /ingest/raw`, `POST /ingest/sync/{platform}`, `GET /ingest/status/{integration_id}`) |
| Tests | `tests/unit/test_cleaning.py`, `tests/unit/test_chunking.py`, `tests/unit/test_embedder.py`, `tests/integration/test_ingestion_pipeline.py`, `tests/integration/test_msgraph_connector.py`, `tests/integration/test_teams_connector.py`, `tests/integration/test_slack_connector.py`, `tests/integration/test_fathom_connector.py` |

**Decisiones clave:**
- Dedup por `(user_id, source, source_id)` — re-sync actualiza en vez de duplicar
- Embedding en batch (hasta 2048 textos por llamada OpenAI) + exponential backoff
- `POST /ingest/raw` es clave para testing sin credenciales reales
- Conectores son stateless: leen `last_sync_at` de `integrations`, fetchean solo lo nuevo

**Verificación:** Tests pass + `POST /ingest/raw` crea documents con embeddings en DB

---

## Phase 4: RAG Retrieval y Cross-Platform Querying (MVP Feature 3)

**Objetivo**: Búsqueda semántica + endpoint de consultas en lenguaje natural con respuestas grounded en contexto.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Retrieval | `app/services/retrieval/__init__.py`, `app/services/retrieval/search.py` (semantic_search: embed query + pgvector + metadata filters), `app/services/retrieval/filters.py` (SearchFilters: date_from/to, source, author) |
| LLM | `app/services/llm/__init__.py`, `app/services/llm/claude_client.py` (async wrapper Anthropic API + retry), `app/services/llm/prompts.py` (RAG_SYSTEM_PROMPT, RAG_USER_TEMPLATE) |
| API | `app/api/routers/query.py` (`POST /query`), `app/api/schemas/query.py` (QueryRequest, QueryResponse, DocumentSource) |
| Tests | `tests/unit/test_retrieval.py`, `tests/unit/test_claude_client.py`, `tests/unit/test_prompts.py`, `tests/integration/test_search.py`, `tests/e2e/__init__.py`, `tests/e2e/test_cross_platform_query.py` |

**Decisiones clave:**
- Búsqueda híbrida en una sola query: pgvector cosine similarity + filtros SQLAlchemy sobre JSONB
- Prompt instruye a Claude a responder solo basado en contexto recuperado (anti-hallucination)
- Response incluye source traceability (qué chunks se usaron)
- Threshold de similaridad: 0.5 (configurable)

**Verificación:** Tests pass + manual: ingestar texto via `/ingest/raw`, query via `/query`, obtener respuesta grounded

---

## Phase 5: Commitment Detection y Tracking (MVP Feature 1)

**Objetivo**: Detección automática de promesas durante la ingesta. Extracción de due dates y prioridades.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Detection | `app/services/commitments/__init__.py`, `app/services/commitments/detector.py` (usa Claude para analizar texto, devuelve JSON estructurado), `app/services/commitments/prompts.py` (COMMITMENT_DETECTION_PROMPT con few-shot examples) |
| Tests | `tests/unit/test_commitment_detection.py`, `tests/integration/test_commitment_pipeline.py`, `tests/e2e/test_commitment_tracking.py` |

**Modificar:**
- `app/services/ingestion/pipeline.py` — después de embed+store, correr commitment detection
- `app/api/routers/commitments.py` — agregar `GET /commitments/pending`, `GET /commitments/overdue`

**Decisiones clave:**
- Detección vía Claude (no regex) — el lenguaje de promesas es demasiado variado
- Due dates son relativas al `metadata.timestamp` del mensaje original, no al momento de ingesta
- Soporta inglés y español
- Few-shot examples incluyen true positives Y false positives (condicionales no son compromisos)
- Para MVP, detección corre síncrona en el pipeline (volumen bajo)

**Verificación:** Tests pass + manual: ingestar "I'll send you the report by next Monday", verificar commitment en `GET /commitments/pending`

---

## Phase 6: Daily Briefing y Agent Orchestration (MVP Feature 2)

**Objetivo**: LangChain agent con tools + sistema de Daily Briefing + scheduler. Fase capstone que integra todo.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Agent Tools | `app/services/agent/__init__.py`, `app/services/agent/tools/__init__.py`, `app/services/agent/tools/memory_retriever.py`, `app/services/agent/tools/task_manager.py`, `app/services/agent/tools/calendar_sync.py`, `app/services/agent/tools/style_analyzer.py` |
| Agent Core | `app/services/agent/agent.py` (LangChain agent con Claude + 4 tools) |
| Briefing | `app/services/briefing/__init__.py`, `app/services/briefing/generator.py` (orquesta calendar + commitments + memory search → Claude → briefing), `app/services/briefing/prompts.py` (BRIEFING_SYSTEM_PROMPT), `app/services/briefing/scheduler.py` (APScheduler para cron) |
| API | `app/api/routers/agent.py` (`POST /agent/query`), `app/api/routers/briefing.py` (`GET /briefing/{user_id}`, `POST /briefing/{user_id}/schedule`), `app/api/schemas/briefing.py` (BriefingResponse: agenda, pending_commitments, contextual_alerts, generated_at) |
| Tests | `tests/unit/test_briefing.py`, `tests/unit/test_agent.py`, `tests/integration/test_briefing_generation.py`, `tests/e2e/test_daily_briefing.py`, `tests/e2e/test_agent_query.py`, `tests/performance/__init__.py`, `tests/performance/test_benchmarks.py`, `tests/security/__init__.py`, `tests/security/test_security.py` |

**Modificar:** `app/main.py` (registrar routers + start scheduler en lifespan), `requirements.txt` (agregar apscheduler)

**Decisiones clave:**
- `/agent/query` (agentic, multi-tool) es distinto de `/query` (RAG directo, más rápido)
- "Contextual Alerts" es la feature de mayor valor: cross-reference calendar participants con commitments pendientes
- Scheduler usa APScheduler in-process (suficiente para MVP single-user; producción → Celery + Redis)
- System prompt del agent incorpora la `identity` del usuario (persona, tono, heurísticas)

**Verificación:**
- `pytest tests/` — todos los tests pasan
- `pytest --cov=app --cov-report=term-missing` — coverage >= 80%
- Manual: crear usuario, ingestar datos con promesas, generar briefing → recibir resumen estructurado con agenda, pendientes, y alertas contextuales

---

## Resumen por Fase

| Fase | Entregable | Archivos nuevos | Tests |
|---|---|---|---|
| 1 | Config + DB + Models + Migrations | ~20 | 4 |
| 2 | CRUD API + Auth scaffolding | ~10 | 5 |
| 3 | Ingestion pipeline + Connectors | ~10 | 7 |
| 4 | RAG search + Query endpoint | ~6 | 5 |
| 5 | Commitment detection automática | ~3 | 3 |
| 6 | Agent + Daily Briefing + Scheduler | ~12 | 6 |

**Archivos críticos** (tocan todo el sistema):
- `app/core/config.py` — settings que todo módulo consume
- `app/core/database.py` — async engine/session, pgvector
- `app/services/ingestion/pipeline.py` — flujo central de datos
- `app/services/retrieval/search.py` — búsqueda híbrida, alimenta query y agent
- `tests/conftest.py` — fixtures compartidas por todos los tests
