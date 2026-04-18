# QA Plan: AI Chief of Staff — MVP

## Objetivo

Definir la estrategia de testing para garantizar la calidad del MVP antes de cada release. Cubre unit tests, integration tests, y E2E tests alineados a las 3 features core del MVP.

---

## 1. Stack de Testing

| Herramienta | Uso |
|---|---|
| `pytest` | Framework principal de tests |
| `pytest-asyncio` | Tests de funciones async (FastAPI, conectores) |
| `pytest-cov` | Cobertura de código |
| `httpx` | Test client para endpoints FastAPI |
| `factory-boy` | Factories para generar datos de test |
| `respx` / `responses` | Mock de llamadas HTTP externas (Slack, MSGraph, OpenAI) |
| `testcontainers` | PostgreSQL + pgvector real para integration tests |

---

## 2. Niveles de Testing

### 2.1 Unit Tests

Tests aislados sin dependencias externas. Mocks para DB, APIs externas, y embeddings.

#### Models & Schema
- [ ] Validación de cada modelo Pydantic (Users, Identities, Integrations, Documents, Commitments)
- [ ] Validación de enums: `platform` ('slack', 'outlook', 'teams', 'fathom'), `status` ('pending', 'completed', 'cancelled')
- [ ] Constraints: email único en `users`, `user_id` FK válido, `embedding` dimension = 1536
- [ ] Serialización/deserialización de campos JSONB (`metadata`, `heuristics`)

#### Services — Ingestion Pipeline
- [ ] **Cleaning**: Remoción de firmas de email, boilerplate de Slack, headers de Teams
- [ ] **Chunking**: Verificar que `RecursiveCharacterTextSplitter` genera chunks de 500-1000 tokens
- [ ] **Chunking edge cases**: Texto vacío, texto menor a un chunk, texto con solo whitespace
- [ ] **Metadata extraction**: Extracción correcta de author, timestamp, project_id, thread_id

#### Services — Commitment Detection
- [ ] Detección de promesas explícitas: "I'll send the file by Friday", "Te lo mando mañana"
- [ ] Detección de promesas implícitas: "Let me check and get back to you"
- [ ] Extracción de due_date cuando está presente
- [ ] No falsos positivos en frases condicionales: "I would send it if..."
- [ ] Asignación correcta de prioridad

#### Services — Daily Briefing
- [ ] Generación del briefing con agenda vacía (sin meetings)
- [ ] Generación con commitments pendientes
- [ ] Generación con alertas contextuales (commitment + meeting con la misma persona)
- [ ] Respeto del timezone del usuario para la fecha del briefing

#### Services — RAG / Retrieval
- [ ] Construcción correcta del query embedding
- [ ] Filtrado por metadata (date range, person, source)
- [ ] Ranking de resultados por similaridad
- [ ] Manejo de query sin resultados relevantes (threshold > 0.5)

#### API Endpoints
- [ ] `GET /` — Health check retorna status y message
- [ ] Endpoints CRUD de usuarios — validación de input, respuestas correctas
- [ ] Endpoints de commitments — crear, listar, actualizar status
- [ ] Endpoints de ingestion — trigger de sync por plataforma
- [ ] Endpoints de query — búsqueda semántica cross-platform
- [ ] Endpoint de daily briefing — generación on-demand
- [ ] Autenticación y autorización en cada endpoint

### 2.2 Integration Tests

Tests contra servicios reales (DB local, APIs mockeadas a nivel HTTP).

#### Database (PostgreSQL + pgvector)
- [ ] Migración completa del schema sin errores
- [ ] CRUD completo en cada tabla (users, identities, integrations, documents, commitments)
- [ ] Búsqueda vectorial: `embedding <=> query_vector` retorna resultados ordenados por similaridad
- [ ] Búsqueda vectorial con filtro de metadata combinado
- [ ] Índices de performance en `documents.embedding` (IVFFlat o HNSW)
- [ ] Cascade deletes: eliminar user elimina sus documents y commitments
- [ ] Concurrencia: upserts simultáneos en `documents` no generan duplicados

#### Conectores Externos (HTTP mocked)
- [ ] **MSGraphConnector**: OAuth2 flow completo (auth code → token → refresh)
- [ ] **MSGraphConnector**: Paginación de emails y eventos de calendario
- [ ] **MSGraphConnector**: Manejo de token expirado → refresh automático
- [ ] **TeamsConnector**: Lectura de chats 1:1 y grupales via MS Graph API
- [ ] **TeamsConnector**: Paginación con `@odata.nextLink`
- [ ] **TeamsConnector**: Rate limiting (429) → retry con backoff exponencial
- [ ] **TeamsConnector**: Filtrado de mensajes del sistema (`messageType != "message"`)
- [ ] **TeamsConnector**: Manejo de `from: null` (mensajes de bot/sistema)
- [ ] **SlackConnector**: Lectura de channels y DMs con Bot Token
- [ ] **SlackConnector**: Paginación con cursor
- [ ] **SlackConnector**: Rate limiting (429) → retry con backoff
- [ ] **FathomConnector**: Importación de transcripts desde API/export
- [ ] Todos los conectores: manejo de errores de red (timeout, 500, connection refused)
- [ ] Todos los conectores: `last_sync_at` se actualiza correctamente en `integrations`

#### Pipeline End-to-End (Ingestion)
- [ ] Conector → Cleaning → Chunking → Embedding (mocked) → Storage en DB
- [ ] Verificar que `source_id` previene duplicados en re-sync
- [ ] Verificar que metadata se preserva a lo largo del pipeline

### 2.3 E2E Tests

Tests de flujos completos de usuario, simulando el uso real.

#### Feature 1: Commitment Tracking
- [ ] Ingestar un email con promesa → commitment aparece en lista con status `pending`
- [ ] Ingestar un mensaje de Slack con promesa + fecha → commitment tiene `due_date` correcto
- [ ] Marcar commitment como `completed` → no aparece en Daily Briefing
- [ ] Commitment vencido → aparece como prioridad alta en briefing

#### Feature 2: Daily Briefing
- [ ] Trigger del briefing matutino → incluye agenda del día desde calendar
- [ ] Briefing incluye commitments pendientes ordenados por prioridad
- [ ] Briefing incluye alerta contextual: "Tenés call con X, le prometiste Y ayer en Slack"
- [ ] Briefing con datos vacíos (sin meetings, sin commitments) → mensaje apropiado

#### Feature 3: Cross-Platform Querying
- [ ] Query: "What was decided about the budget?" → respuesta combina datos de email + transcript
- [ ] Query con filtro temporal: "Last week's discussions about Project X"
- [ ] Query sobre persona: "What did John commit to?" → filtra por author en metadata
- [ ] Query sin resultados → respuesta clara indicando que no hay información

---

## 3. Tests No Funcionales

### Performance
- [ ] Búsqueda vectorial en `documents` con 10K registros responde en < 500ms
- [ ] Ingestion pipeline procesa 100 emails en < 60s (excluyendo embedding API)
- [ ] Daily Briefing se genera en < 10s
- [ ] API endpoints responden en < 200ms (excluyendo LLM calls)

### Seguridad
- [ ] Tokens OAuth2 se almacenan encriptados en `integrations`, nunca en plaintext
- [ ] No se exponen tokens en logs ni respuestas de API
- [ ] Filtro de PII funciona: números de tarjeta y passwords no se almacenan en `documents`
- [ ] Cada usuario solo accede a sus propios datos (row-level isolation por `user_id`)
- [ ] Rate limiting en endpoints públicos
- [ ] Input sanitization: queries de usuario no permiten injection (SQL o prompt)

### Reliability
- [ ] Si un conector falla, los demás siguen funcionando
- [ ] Si OpenAI Embeddings no responde, el pipeline reintenta con backoff exponencial
- [ ] Si Claude API no responde, el briefing retorna error graceful, no crash
- [ ] Sync parcial: si falla a mitad de ingesta, lo procesado se mantiene y se puede resumir

---

## 4. Estructura de Archivos de Test

```
tests/
├── conftest.py              # Fixtures globales (DB, test client, factories)
├── factories.py             # Factory Boy definitions
├── unit/
│   ├── test_models.py
│   ├── test_cleaning.py
│   ├── test_chunking.py
│   ├── test_commitment_detection.py
│   ├── test_briefing.py
│   └── test_retrieval.py
├── integration/
│   ├── test_database.py
│   ├── test_msgraph_connector.py
│   ├── test_teams_connector.py
│   ├── test_slack_connector.py
│   ├── test_fathom_connector.py
│   └── test_ingestion_pipeline.py
├── e2e/
│   ├── test_commitment_tracking.py
│   ├── test_daily_briefing.py
│   └── test_cross_platform_query.py
├── performance/
│   └── test_benchmarks.py
└── security/
    └── test_security.py
```

---

## 5. Criterios de Aceptación por Release

| Criterio | Umbral |
|---|---|
| Unit test coverage | >= 80% |
| Integration tests passing | 100% |
| E2E tests passing (happy path) | 100% |
| Security tests passing | 100% |
| Performance benchmarks met | >= 90% de los scenarios |
| Zero vulnerabilidades críticas | OWASP Top 10 |

---

## 6. CI/CD Integration

- Tests se ejecutan en cada PR via GitHub Actions
- Pipeline: `lint` → `type-check (mypy)` → `unit tests` → `integration tests` → `e2e tests`
- Integration tests requieren servicio PostgreSQL+pgvector (Docker en CI)
- Coverage report se publica como comment en el PR
- Merge bloqueado si coverage baja del umbral o algún test falla
