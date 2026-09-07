# Plan: Backoffice del sistema multi-agente de conocimiento

**Status**: Fases 0-6 implementadas en `feat/knowledge-backoffice`, con code review y fixes
aplicados en cada checkpoint. Pendiente: merge a `main`.

## Goal

El sistema multi-agente de conocimiento (`specs/plan-multi-agent-knowledge.md`, ya en `main`) corre
seis agentes de dominio, una escalera de resolución de dudas y un motor de reconciliación — pero
todo eso era una caja negra: sin traza persistida de qué hizo cada agente, y con modelo/prompt/tools
hardcodeados en código. Este plan agrega un backoffice web que permite (a) **observar** las
corridas — iteraciones, tool calls, negociaciones entre agentes, conclusiones, costo — y (b) **ver
y configurar** cada agente: modelo, system prompt, tools habilitadas y servidores MCP, con alta de
MCPs nuevos desde la UI.

---

## Decisiones de diseño

- **Frontend**: HTML/JS estático servido por FastAPI (`StaticFiles`), mismo patrón que
  `static/voice/` — sin build tooling, sin `package.json`. Librerías de terceros (Chart.js,
  Cytoscape.js) por CDN, igual que `marked`/`DOMPurify` en el voice UI.
- **Configuración de agentes**: registro curado de las tools existentes (habilitar/deshabilitar por
  agente) + alta de servidores MCP como fuente de tools nuevas. **No** se ejecuta código Python
  subido desde la UI — la superficie de riesgo se mantiene acotada a lo que ya corre en producción.
- **Curación del grafo**: lectura + responder/descartar preguntas escaladas al humano. Sin edición
  destructiva de entidades/claims — el sistema se corrige vía respuestas del humano y reconciliación,
  como fue diseñado originalmente, no por edición manual del grafo.
- **Invariante central**: un usuario sin filas de configuración (`AgentConfig`, `McpServer`) tiene el
  comportamiento exacto de antes de este plan. Nada cambia hasta que el usuario guarda un override
  explícito desde el backoffice.

---

## Arquitectura — piezas nuevas

```
┌─────────────────────────────────────────────────────────────────┐
│  UI estática (static/backoffice/) — 6 vistas                     │
│  Dashboard · Agentes · Runs/Trazas · Grafo · Preguntas · MCPs    │
└───────────────────────────▲───────────────────────────────────────┘
                             │ /backoffice/* (REST)
┌───────────────────────────┴───────────────────────────────────────┐
│  API (app/api/routers/backoffice.py)                               │
│  Config de agentes · Catálogo de tools · CRUD de MCPs · Runs/     │
│  trazas · Grafo (entidades/claims/preguntas)                      │
└───────────────────────────▲───────────────────────────────────────┘
                             │
┌───────────────────────────┴───────────────────────────────────────┐
│  Servicios nuevos                                                  │
│  tracing.py (persiste runs/eventos) · agent_config_service.py     │
│  (config efectiva) · mcp_server_service.py (CRUD + cifrado) ·     │
│  tool_registry.py (catálogo) · run_query_service.py (lectura)     │
└───────────────────────────▲───────────────────────────────────────┘
                             │ enganchado en, sin cambiar el contrato de:
┌───────────────────────────┴───────────────────────────────────────┐
│  Sistema existente (specs/plan-multi-agent-knowledge.md)          │
│  domain_agent.py · rd_agent.py · reconciliation.py ·              │
│  swarm_negotiation.py · strands_orchestrator.py · scheduler.py    │
└─────────────────────────────────────────────────────────────────┘
```

### Trazas persistidas (`agent_runs` / `agent_run_events`)

Cada invocación de un agente (domain agent, rd agent, reconciliation, negociación, chat) crea una
fila `AgentRun`; su conversación completa (texto, tool calls, tool results) se serializa desde
`agent.messages` a filas `AgentRunEvent` ordenadas. Una negociación de swarm (`ask_peer_agents`,
`negotiate_same_as`) queda como sub-run enlazada por `parent_run_id`, con eventos de `handoff` (el
orden real de `SwarmResult.node_history`) y `verdict`.

**Invariante de aislamiento**: `tracing.py` abre su propia `AsyncSession` (nunca la del caller) y
nunca propaga una excepción — un fallo de tracing no puede tumbar una corrida real. En producción
(Postgres, pool de conexiones real) esto da aislamiento transaccional genuino; en el harness de
tests (SQLite in-memory con `StaticPool`, una sola conexión compartida) esa independencia no es
verificable — documentado explícitamente en el docstring del módulo y fijado por
`TestSharedTestConnectionCaveat` en `tests/unit/test_tracing.py`, para que no se confunda con una
garantía real.

### Configuración efectiva (`agent_configs`)

`agent_config_service.get_effective_config()` mergea una fila `AgentConfig` (si existe) sobre los
defaults del código — cada campo `NULL` en la fila cae al default, no a vacío. `make_domain_agent`
y `StrandsOrchestrator._build_agent` siguen siendo síncronos a propósito (resolver la config
requiere un `await`); las funciones async que sí pueden esperar (`run_domain_agent`, `query()`)
resuelven la config y la pasan ya armada. El orchestrator es el único caso donde `system_prompt` del
override se ignora deliberadamente — el prompt real se compone dinámicamente por request
(identidad, estilo, fecha) y una fila reemplazándolo perdería esa personalización.

### Servidores MCP (`mcp_servers`)

Igual patrón que `Integration.access_token`: la API key se cifra con Fernet
(`app/utils/encryption.py`) en la capa de servicio, nunca en el modelo, nunca devuelta por la API
(`McpServerRead` la omite, solo expone `has_api_key: bool`). `rd_agent._build_mcp_client` resuelve
el servidor desde `AgentConfig.mcp_server_ids` (solo el primero — un agente corre una sola conexión
MCP por invocación) y cae a `id_brain_mcp_url`/`id_brain_mcp_api_key` (el bootstrap de `.env`) si no
hay ninguno configurado o el referenciado está deshabilitado/borrado. `EXCLUDED_MCP_TOOLS` se suma
siempre al `rejected` del servidor, sin importar su propio `allowed_tools` — Strands aplica
`allowed` primero y `rejected` después, así que un `allowed_tools` mal configurado nunca puede
reexponer `create_tasks`.

### Retención (`trace_retention_days`)

`tracing.prune_traces()` borra las filas `AgentRun` (y en cascada sus eventos, vía
`ON DELETE CASCADE`) más viejas que `settings.trace_retention_days` (default 30). Corre como un paso
más de `KnowledgeAgentScheduler._run_cycle`, con el mismo aislamiento de fallas por paso que el
resto del ciclo — independiente de si `enable_knowledge_agents` generó filas nuevas ese ciclo o no.

---

## Modelo de datos nuevo

| Tabla | Campos clave | Para qué |
|---|---|---|
| `agent_runs` | `agent_key`, `run_type`, `trigger`, `status`, `model_id`, `started_at`/`finished_at`/`duration_ms`, tokens, `summary`, `error`, `stats` (JSONB), `parent_run_id` | Una fila por invocación de agente/swarm. |
| `agent_run_events` | `run_id`, `seq`, `event_type` (assistant_text/tool_call/tool_result/handoff/verdict/error), `actor`, `tool_name`, `payload` (JSONB, truncado) | La conversación completa, ordenada, de una corrida. |
| `agent_configs` | `user_id` + `agent_key` (único), `enabled`, `model_id`, `system_prompt`, `enabled_tools`, `mcp_server_ids`, `params` — todos nullable | Override parcial sobre los defaults del código. |
| `mcp_servers` | `user_id`, `name`, `url`, `auth_header`, `api_key_encrypted`, `enabled`, `allowed_tools`/`rejected_tools`, `last_checked_at`/`last_status`/`discovered_tools` | Servidores MCP administrados por el usuario, alternativa a las env vars. |

---

## Fases

### Fase 0 — Esquema ✅
- [x] Migración `013_add_backoffice_tables.py`: 4 tablas + 4 enums nuevos, mismo estilo que
  `011`/`012` (`create_type=False` + `create(bind, checkfirst=True)`, `downgrade()` simétrico).
- [x] Modelos SQLAlchemy + DDL SQLite en `tests/conftest.py`.

**Complejidad**: baja — sigue el patrón ya establecido en Phase 0 del plan del grafo de conocimiento.

### Fase 1 — Trazas ✅
- [x] `app/services/agent/tracing.py`: `start_run`/`finish_run`/`record_agent_events`/
  `record_swarm_negotiation`/`record_verdict_event`. Enganchado en `run_domain_agent`,
  `run_rd_domain_agent`, `run_reconciliation`, `_ask_peer_agents`, `negotiate_same_as`,
  `StrandsOrchestrator.query`. `run_negotiation` (swarm_negotiation.py) pasa de descartar el
  `SwarmResult` a devolverlo.
- [x] Manejo de `asyncio.CancelledError` en los 5 puntos de enganche — sin esto, un run cancelado
  (cliente SSE desconectado, shutdown mid-ciclo) dejaba una fila `AgentRun` huérfana en `RUNNING`
  para siempre.
- [x] Tests: `tests/unit/test_tracing.py` (20 tests) — serialización de mensajes, truncado,
  sequencing entre llamadas, extracción de `usage` sin romper `finish_run` ante un objeto
  malformado, y el caveat de aislamiento de sesión en el harness de SQLite.

**Complejidad**: media — el hallazgo no trivial fue que `getattr(...)` con default solo atrapa
`AttributeError`; la extracción de `usage` se movió adentro del `try/except` de `finish_run` en vez
de calcularse afuera, en el code review de este checkpoint.

### Fase 2 — Configuración ✅
- [x] `agent_config_service.py`: `EffectiveAgentConfig`, `get_effective_config`,
  `effective_config_from_row` (evita doble query cuando el caller ya tiene la fila),
  `upsert_agent_config` (sentinel `UNSET` para distinguir "campo no mencionado" de "campo puesto en
  null explícitamente"), `filter_tools` (loguea un warning si `enabled_tools` tiene nombres que no
  matchean ninguna tool real).
- [x] `tool_registry.py`: catálogo declarativo, con `make_watermark_tools` extraído de
  `make_domain_agent` (antes inline, no testeable por separado) específicamente para que
  `test_tool_registry.py` pueda diffear contra la implementación real en vez de hardcodear una
  segunda copia de los nombres.
- [x] Tests clave: sin fila de `AgentConfig`, `make_domain_agent`/`_build_agent` construyen el
  agente idéntico a como lo hacían antes de esta fase (`config=None` reproduce el default).

**Complejidad**: media — la restricción de no romper 27+ call sites de test existentes que llaman
`make_domain_agent` sin `await` fue lo que fijó la decisión de resolver la config en el caller async
y pasarla ya armada, en vez de hacer la función misma async.

### Fase 3 — Servidores MCP ✅
- [x] `mcp_server_service.py`: CRUD + cifrado Fernet + `test_connection` (conecta, lista tools,
  nunca persiste — `record_connection_test` es la función separada que sí escribe).
- [x] `rd_agent._resolve_mcp_server` + `_build_mcp_client(server=...)`.
- [x] Fix de seguridad del code review: la construcción de `MCPClient(...)` se movió adentro del
  `try` en ambos call sites — una URL mal formada (`ValueError` en la construcción, no solo en
  `.start()`) rompía el contrato "nunca lanza" de `test_connection` y dejaba un `AgentRun` huérfano
  en `rd_agent`.

**Complejidad**: media-alta — el checkpoint de seguridad de esta fase encontró el problema real
(construcción fuera del try), no solo confirmó lo ya hecho.

### Fase 4 — API ✅
- [x] `app/api/routers/backoffice.py` (18 endpoints) + `app/api/schemas/backoffice.py`.
- [x] Extensiones a `store.py`: paginación/búsqueda en `list_entities`, `count_entities`,
  `list_claims_for_user`, `list_questions`. `run_query_service.py` nuevo para `AgentRun`/`AgentRunEvent`.
- [x] Fixes CRITICAL del code review:
  - `POST /agents/{key}/run` corre sincrónicamente (no hay cola de background jobs en este repo) y
    recupera su propio `run_id` comparando un conteo de runs antes/después — no por timestamp
    (SQLite trunca `CURRENT_TIMESTAMP` a segundos enteros, lo que producía falsos positivos de
    "sin corrida nueva" en runs rápidos).
  - `McpServerCreate.url`/`McpServerUpdate.url` ganaron validación SSRF (rechaza loopback, rangos
    privados/RFC1918, link-local, el endpoint de metadata de cloud) — el Phase 3 review ya había
    marcado esto como riesgo diferido hasta que existiera un endpoint de escritura.

**Complejidad**: alta — de las cinco fases, la que más iteración de code review tuvo (2 CRITICAL +
2 WARNING), justamente por ser la superficie donde el resto de las fases se vuelve alcanzable por
HTTP.

### Fase 5 — UI ✅
- [x] `static/backoffice/{index.html,app.js,style.css}` — 6 vistas, mismo login/tokens de diseño
  que `static/voice/`. `authedFetch()` agrega el manejo de 401 (volver al login) que
  `static/voice/app.js` no tiene.
- [x] `app/main.py`: mount en `/backoffice-ui`. `Dockerfile`: `COPY static/ ./static/` — faltaba
  por completo, así que `/voice-ui` venía devolviendo 404 en producción desde que existe; este fix
  resuelve los dos mounts a la vez.
- [x] Verificación: sin browser disponible en el entorno de desarrollo de esta sesión (la
  automatización no llega a `localhost`), se validó con `curl` contra la base real que cada
  respuesta de la API matchea campo a campo lo que `app.js` espera, más una auditoría manual línea
  por línea de escaping/wiring del DOM, confirmada independientemente por un segundo code review.
- [x] Fixes del code review: CSS del sidebar colapsado ocultaba el badge de preguntas por error de
  selector; `loadGraph` sin try/catch alrededor del render (única vista sin ese patrón); botón de
  guardar del modal de MCP sin deshabilitar durante el request (doble-click → fila duplicada);
  tracking de runs manuales en vuelo por `agent_key` para que navegar lejos y volver no dispare una
  segunda corrida (costo de LLM) del mismo agente.

**Complejidad**: media — sin poder ejecutar el página en un browser real, la verificación se apoyó
en curl contra datos reales + dos pasadas de code review en vez de una sola.

### Fase 6 — Cierre ✅
- [x] `trace_retention_days` (default 30) + `tracing.prune_traces()`, enganchado como paso propio
  de `KnowledgeAgentScheduler._run_cycle`.
- [x] Este documento, actualización de `CLAUDE.md` y `specs/qa-plan.md`.

**Complejidad**: baja.

---

## Riesgos

- **Volumen de trazas**: mitigado por el truncado por payload (`TRACE_MAX_PAYLOAD_CHARS`) y la
  retención de 30 días; sin retención la tabla `agent_run_events` crecería sin techo, dado que un
  `toolResult` puede traer documentos completos.
- **Secretos en trazas**: los argumentos de tools MCP podrían arrastrar credenciales — el recorder
  nunca serializa headers ni la config del cliente MCP, solo el input/output declarado de cada tool.
- **Prompts editables como superficie de prompt-injection**: un agente con tools y un prompt
  editable por el usuario es, en teoría, una superficie de ataque — mitigado por ser un sistema
  personal de un solo usuario, con todo scoped por `user_id`, pero vale tenerlo presente si esto
  algún día deja de ser mono-usuario.
- **Aislamiento transaccional no verificable en tests**: ver la nota de Fase 1 — la garantía real
  depende del pool de conexiones de producción, no de algo que el harness de SQLite pueda probar.
- **Sin cola de background jobs**: `POST /agents/{key}/run` bloquea la request HTTP durante toda la
  corrida (tardaba ~25-30s por batch de 20 documentos en el drain real de Outlook de esta sesión).
  Aceptable para una acción de administración manual; no escalaría a un endpoint de uso frecuente.

---

## Orden y checkpoints

Fase 0 → 1 → code review (aislamiento transaccional + volumen) → 2 → code review (invariante
"sin fila = sin cambio") → 3 → code review (manejo de secretos, encontró el problema real de
`MCPClient` fuera del try) → 4 → code review (encontró los 2 CRITICAL de run_id y SSRF) → 5 → code
review (UI — auditoría manual propia + segunda pasada independiente) → 6. Mismo criterio que el
plan del grafo de conocimiento: cross-check contra `specs/qa-plan.md` después de cada fase, fix de
todos los CRITICAL/WARNING antes de avanzar.
