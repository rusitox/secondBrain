# Plan: Sistema multi-agente de conocimiento unificado

**Status**: Todas las fases (0-8) implementadas en `feat/multi-agent-knowledge`, con code review y
fixes aplicados en los checkpoints marcados. Pendiente: merge a `main`.

## Goal

Construir, sobre el `StrandsOrchestrator` ya en producción, un sistema de agentes de dominio (uno
por fuente de datos: Slack, Outlook, Teams, Fathom, Notion, y a futuro la plataforma de I+D vía su
MCP propio) que interactúan entre sí — sin mediación del orquestador — para ir construyendo una
**fuente de conocimiento unificada, con proveniencia y cada vez más sólida**, sobre la cual el
orquestador responde al usuario. Cuando los agentes no pueden resolver algo solos (ambigüedad de
identidad, contradicción entre fuentes, o simplemente no entienden algo de su propio dominio), el
sistema se lo pregunta al humano en vez de adivinar o perder el dato.

---

## Por qué no es "6 agentes chateando libremente"

Investigación previa a este plan (ver contexto de sesión) encontró dos cosas que cambian el diseño:

1. **El diseño viejo (`MultiAgentOrchestrator`, ya eliminado) no tenía comunicación real entre
   agentes** — `asyncio.gather` puro, aislado, y "escalar al humano" era esperar que una frase
   sobreviviera un synthesis LLM final. Ese patrón falló silenciosamente y es justamente lo que hay
   que evitar repetir.
2. **Strands no da persistencia gratis para diálogo entre agentes.** `Swarm` (el único primitivo
   con memoria compartida real — `SharedContext` — y turnos tipo negociación) vive y muere dentro de
   una sola ejecución. Si 6 agentes negocian libremente en cada corrida sin un lugar persistente
   donde guardar el resultado, están re-negociando lo mismo desde cero cada vez: se gasta LLM y no
   se acumula nada.

Por eso el diseño separa "negociar" (efímero, vía Swarm, acotado a quienes realmente lo necesitan)
de "acumular conocimiento" (persistente, en Postgres, con proveniencia y confianza crecientes).

---

## Arquitectura — 4 capas

```
┌─────────────────────────────────────────────────────────────────┐
│  Capa 4 — Orquestador (StrandsOrchestrator, ya existe)           │
│  Lee el conocimiento consolidado. Surge preguntas pendientes al  │
│  usuario. Las respuestas del usuario vuelven como claims.        │
└───────────────────────────▲───────────────────────────────────────┘
                             │ lee / escribe feedback
┌───────────────────────────┴───────────────────────────────────────┐
│  Capa 3 — Conocimiento persistente (Postgres)                     │
│  entities · entity_claims · entity_links · pending_questions      │
│  Nunca se pisa un dato: todo queda con fuente + confianza.        │
└───────────────────────────▲───────────────────────────────────────┘
                             │ escriben resultados
┌───────────────────────────┴───────────────────────────────────────┐
│  Capa 2 — Reconciliación (scoped, batch, post-sync)                │
│  Match determinístico primero (email/nombre exacto/embedding).    │
│  Casos ambiguos → Swarm acotado (solo los agentes en conflicto).  │
│  Sin consenso → pending_questions.                                 │
└───────────────────────────▲───────────────────────────────────────┘
                             │ proponen candidatos + dudas propias
┌───────────────────────────┴───────────────────────────────────────┐
│  Capa 1 — Agentes de dominio (uno por fuente)                     │
│  Slack · Outlook · Teams · Fathom · Notion · (I+D vía MCP, luego) │
│  Cada uno intenta activamente ENTENDER su dominio: entidades,     │
│  relaciones, temas recurrentes. Si algo no le cierra, pregunta.   │
└─────────────────────────────────────────────────────────────────┘
```

**Principio rector**: cada agente de dominio tiene mandato de dos partes — (a) proponer lo que
entendió con la confianza que le corresponde, y (b) marcar explícitamente lo que NO entendió o le
genera duda, aunque sea dentro de su propia fuente (no solo en conflictos cruzados). Ambas cosas
son ciudadanos de primera clase en el esquema, no un efecto secundario del synthesis final.

### Escalada de resolución de dudas

Una duda **nunca** salta directo al humano. Recorre una escalera, y cada escalón que la resuelve
evita gastar el siguiente:

1. **Consultar el conocimiento ya consolidado** (Capa 3) — antes de tratar algo como desconocido,
   el agente busca en `entities`/`entity_claims` si ya hay algo corroborado que lo resuelve.
2. **Consultar a los agentes pares** — el agente postea la duda; si hay un par claramente relevante
   (ej: la misma persona aparece en Outlook), se dispara un `Swarm` acotado a esos agentes para que
   negocien una respuesta (mismo mecanismo que la reconciliación de Phase 4 — no es un sistema
   aparte, es el mismo invocado proactivamente en vez de reactivamente). Si no hay un par obvio, la
   duda queda abierta para que cualquier agente la retome en su próxima corrida de extracción
   (batch-native, no bloquea).
3. **Proponer y validar con el humano** — si 1-2 producen una respuesta candidata con confianza
   media (ni suficiente para darla por cierta, ni nula), no se le pregunta al humano desde cero: se
   le presenta la candidata para confirmar/corregir ("creemos que X, ¿es así?"). Mayor tasa de
   respuesta útil que una pregunta abierta.
4. **Escalada en blanco** — solo si ningún escalón anterior produjo nada, se genera una pregunta
   sin candidata. Es el último recurso, no el primero.

Esto vive en una sola tabla (`pending_questions`, ver abajo) cuyo ciclo de vida atraviesa los 4
escalones — no son sistemas separados.

---

## Modelo de datos nuevo

Reemplaza el campo `entities` (JSON libre, nunca leído) de la tabla `memories` actual por un
esquema real con proveniencia:

| Tabla | Campos clave | Para qué |
|---|---|---|
| `entities` | `entity_type` (person/project/initiative/topic/org), `canonical_name`, `aliases[]`, `attributes` (JSONB), `embedding`, **`confidence`** | La entidad canónica. `confidence` es la métrica de "solidez" — sube con corroboración entre fuentes y confirmación humana. |
| `entity_claims` | `entity_id`, `source`, `source_ref`, `claim_text`, `confidence`, `status` (active/superseded/disputed/confirmed_by_user), `asserted_by_agent` | Qué dijo cada fuente sobre cada entidad. Nunca se sobreescribe — una contradicción queda visible, no se pierde. |
| `entity_links` | `entity_id_a`, `entity_id_b`, `relation_type` (same_as/works_on/manages/related_to), `confidence`, `resolved_by` (deterministic/swarm/user) | Relaciones entre entidades, incluidas las fusiones ("estas dos son la misma persona"). |
| `pending_questions` | `raised_by_agent`, `question_text`, `context` (JSONB), `target` (peer_agents/human), `candidate_answer`, `candidate_confidence`, `status` (open/answered/dismissed), `resolved_by` (knowledge_base/peer_swarm/human), `answer_text` | El ciclo de vida completo de una duda: nace apuntando a `peer_agents`, escala a `human` solo si nadie pudo resolverla, y siempre intenta llevar una `candidate_answer` para validar en vez de preguntar en blanco. |

`entities.confidence` se recalcula en la reconciliación: sube con cada fuente independiente que
corrobora, sube fuerte con confirmación humana, baja si aparece un claim `disputed` sin resolver.
Esto le da un número concreto y verificable a "cada vez más sólida" en vez de quedar como aspiración.

---

## Mapeo a primitivas de Strands

| Necesidad | Primitiva | Nota |
|---|---|---|
| Agente de dominio que entiende su fuente | `Agent` + tools propios (mismo patrón `strands_tools.py` ya usado) | Uno por fuente, corre en background, no en el request path del chat. |
| Negociación acotada entre 2-3 agentes en conflicto | `strands.multiagent.Swarm` + `SharedContext` | Único primitivo con memoria compartida real. Se instancia ad-hoc solo con los agentes involucrados en ESE conflicto puntual — nunca los 6 juntos. |
| Resolver una duda propia consultando pares antes que al humano | `strands.multiagent.Swarm` + `SharedContext`, invocado **proactivamente** por el agente con la duda (mismo mecanismo que la reconciliación de Phase 4, no uno nuevo) | Se dispara solo si hay un par plausible; si no, la duda queda abierta para la próxima corrida en vez de gastar un swarm sin destinatario claro. |
| Validar con el humano como último recurso | Tool propio `escalate_or_validate` → escribe/actualiza `pending_questions`, siempre con `candidate_answer` si el escalón 1-2 produjo algo (inspirado en `strands_tools.handoff_to_user`, pero async/batch, no bloqueante) | No bloquea la corrida del agente — sigue procesando el resto y deja la pregunta anotada. |
| Orquestador responde al usuario con lo consolidado | Nuevo tool `query_knowledge` en `strands_tools.py`, sumado a los existentes | Convive con `search_memory`; no lo reemplaza (uno es RAG crudo, el otro es la vista consolidada con proveniencia). |

---

## Modelo de ejecución

Background/batch, desacoplado del chat en vivo (decisión ya tomada): los agentes de dominio y la
reconciliación corren disparados por el scheduler de sync existente (`app/services/sync/scheduler.py`),
después de cada ciclo de sync por fuente. El `StrandsOrchestrator` del chat solo LEE lo consolidado
— no espera a que ningún agente de dominio corra en el momento de responder.

---

## Fases

### Phase 0 — Esquema base ✅
- [x] Migración Alembic: `entities`, `entity_claims`, `entity_links`, `pending_questions`
  (`alembic/versions/011_add_knowledge_tables.py`, `012_add_processed_documents.py`).
- [x] Modelos SQLAlchemy en `app/models/` (siguiendo `UUIDMixin`/`TimestampMixin` existentes).
- [x] Sin lógica de agentes todavía — solo esquema + CRUD helpers (`store.py`) + tests de modelo.

**Complejidad**: baja. Prerequisito de todo lo demás.

### Phase 1 — Agente de dominio: implementación de referencia (Slack) ✅
- [x] `app/services/agent/knowledge/domain_agent.py`: factory `make_domain_agent(source, ...)` —
  un Strands `Agent` cuyo mandato es leer `Document` rows nuevos de esa fuente, proponer
  entidades/claims a la Capa 3, autoevaluar su confianza, y recorrer la escalera de resolución
  (consultar conocimiento existente → consultar pares vía swarm si hay uno plausible → validar con
  el humano con una candidata → escalada en blanco) cuando algo no le cierra, sin necesidad de que
  sea un conflicto cruzado — puede dudar de algo puramente dentro de su propia fuente.
- [x] Tools propios (nombres finales, distintos del borrador inicial): `find_or_create_entity`,
  `add_claim`, `consult_knowledge_base`, `ask_peer_agents` (dispara el swarm acotado),
  `escalate_or_validate`, `get_unprocessed_documents`, `mark_document_processed`.
- [x] Implementación completa + tests para Slack como referencia.
- [x] Disparo manual: `scripts/run_domain_agent.py`.

**Complejidad**: alta — es el patrón que todo lo demás reutiliza. Code review completo hecho acá
antes de replicar.

### Phase 2 — Réplica a Outlook, Teams, Fathom ✅
- [x] Reusar la factory de Phase 1; ajustar el prompt de extracción por fuente (ej: Outlook tiene
  eventos de calendario además de emails; Fathom son transcripciones de reuniones más largas).
- [x] Tests por fuente.

**Complejidad**: media — mecánica, no de diseño.

### Phase 3 — Notion ✅
- [x] Fase separada porque `app/services/notion/` ya tiene sync bidireccional y publisher propios.
  El agente de dominio acá es de **solo lectura** hacia la Capa 3 — no debe escribir de vuelta a
  Notion ni interferir con `NotionSync`.

**Complejidad**: media, con cuidado de no pisar la integración existente.

### Phase 4 — Motor de reconciliación ✅ (code review completo, hallazgos corregidos)
- [x] Pre-filtro determinístico: email exacto → auto-link como `same_as` sin gastar LLM.
  ("Nombre exacto" quedó cubierto por construcción: `find_or_create_entity` de Phase 1 ya
  busca entre todas las entidades del usuario, no solo las de su fuente, así que dos
  entidades separadas con el mismo nombre exacto ya no pueden existir — el único
  duplicado real que llega a reconciliación es ambigüedad genuina entre fuentes.)
- [x] Zona ambigua → similaridad de embedding (`store.find_similar_entities`, requiere pgvector)
  + mismo mecanismo de `Swarm` acotado que usa `ask_peer_agents` (Phase 1) — la reconciliación
  es la invocación *reactiva* (por lote, detectando candidatos) del mismo mecanismo que un agente
  dispara *proactivamente* cuando tiene una duda propia. Un solo código de negociación, dos gatillos.
- [x] Sin consenso (swarm no converge) → `pending_questions` con `target=human` y
  `candidate_answer` si el swarm llegó a algo parcial, nunca una pregunta en blanco si evitable.
  Un par con pregunta ya abierta se salta en la próxima corrida en vez de re-negociar.
- [x] Recalcular `entities.confidence` según corroboración (heurística v1, documentada).
- [ ] Disparo: **no enganchado al scheduler todavía** — cada integración sincroniza en su propio
  intervalo independiente, así que "después de un ciclo de sync" no tiene un único punto de
  disparo obvio sin antes decidir cadencia/costo con el usuario. Corre manual por ahora vía
  `scripts/run_reconciliation.py`.

**Complejidad**: alta — es el corazón de "los agentes se ponen de acuerdo entre ellos". Code review
obligatorio, con foco en costo (cuántos swarms se disparan por ciclo) y en que el pre-filtro
determinístico realmente reduce el volumen antes de gastar LLM.

### Phase 5 — Orquestador: lectura + feedback loop ✅ (code review completo, hallazgos corregidos)
- [x] Tool `query_knowledge(entity_or_topic)` en `strands_tools.py`.
- [x] El orquestador surge `pending_questions` abiertas en la conversación cuando es relevante
  (tool `get_pending_questions`, instrucción explícita en el system prompt).
- [x] La respuesta del usuario se escribe como `entity_claims` con `asserted_by_agent="user"` y
  `status=confirmed_by_user`, sube la confianza de la entidad, y cierra la `pending_question`
  (tool `confirm_pending_answer`). También maneja preguntas de "¿son la misma entidad?" de
  reconciliación creando el `entity_link` `same_as` en vez de un claim.
- [x] Hallazgo no planeado corregido: `StrandsOrchestrator` (el orquestador de chat en producción,
  mergeado desde antes de este plan) no usaba `SequentialToolExecutor` — mismo bug de concurrencia
  de sesión que se había corregido en los agentes de dominio durante el code review de Phase 1,
  pero sin corregir en código ya en producción. Corregido acá al notar que las tools nuevas
  comparten la misma `AsyncSession`.

**Complejidad**: media.

### Phase 6 — Agente de I+D (plataforma propia vía MCP) ✅
- [x] Probado el MCP en vivo (`i-d-mcp`, transporte HTTP streamable): 14 tools — 13 de lectura
  (`list_initiatives`, `get_initiative`, `list_tasks`, `get_task_activity_summary`, `list_projects`,
  `list_publications`, `list_news`, `list_okrs`, `list_team`, `list_commercial_meetings`,
  `list_trainings`, `get_monthly_plan`, `search_knowledge`) + 1 de escritura (`create_tasks`,
  auto-documentada por el server como la única tool de escritura).
- [x] Decisión explícita del usuario (no aplanar a "documentos"): el agente accede directo a las
  tools nativas del MCP en vez de un `get_unprocessed_documents` genérico — no hay tabla
  `documents` ni watermark persistido; cada corrida vuelve a explorar el estado vigente y confía en
  el dedup existente de `find_or_create_entity` para no duplicar entidades ya vistas.
- [x] `create_tasks` nunca se expone al agente: excluida vía `MCPClient(tool_filters={"rejected":
  [...]})` en la conexión, y re-afirmada ausente después de `list_tools_sync()` (assert) como
  defensa en profundidad ante un cambio futuro del catálogo del server.
- [x] `app/services/agent/knowledge/domain_agent.py`: extraída `make_resolution_ladder_tools()`
  (find_or_create_entity, add_claim, consult_knowledge_base, ask_peer_agents, escalate_or_validate)
  de `make_domain_agent`, reutilizada por el agente de I+D sin duplicar la escalera de resolución.
  `REGISTERED_SOURCES` ahora incluye `"rd"` a mano (no se puede derivar de `Platform`, no es un
  connector).
- [x] `app/services/agent/knowledge/rd_agent.py` (nuevo): `run_rd_domain_agent(db, user_id,
  embedder=None)` — conecta el `MCPClient`, valida la exclusión de `create_tasks`, arma el Agent con
  las tools del MCP + la escalera de resolución (`SequentialToolExecutor`, mismo motivo que el resto:
  todas las tools comparten un único `AsyncSession`), y maneja el ciclo de vida `start()`/`stop()`
  alrededor de todo el `invoke_async`. No-op explícito si `id_brain_mcp_url` no está configurado.
- [x] `scripts/run_rd_domain_agent.py` (nuevo) — disparador manual, sin `--batch-size` (no aplica:
  no hay cola de documentos). `scripts/run_domain_agent.py` excluye `"rd"` de sus `--source` choices
  a propósito.
- [x] Tests: `tests/integration/test_rd_agent.py` — mockea `MCPClient`/`Agent` (nunca red real),
  cubre: no-op sin configurar, exclusión de `create_tasks` en las tools que llegan al Agent, el
  assert de defensa en profundidad si igual se filtrara, y que la escalera de resolución comparte
  el mismo `db_session` real (no un duplicado hardcodeado).
- [x] Credenciales del MCP (`id_brain_mcp_url`, `id_brain_mcp_api_key`) sólo como nombres de campo en
  `app/core/config.py` — los valores reales viven únicamente en el `.env` del usuario, nunca en el
  repo (ni código, ni tests, ni este plan).

**Complejidad**: media — resuelta reutilizando la escalera de resolución existente; lo nuevo fue la
integración con `MCPClient` y su ciclo de vida.

### Phase 7 — Observabilidad de solidez ✅
- [x] `app/services/agent/knowledge/store.py`: `get_knowledge_stats(db, user_id,
  merged_window_hours=24)` — todo agregado en SQL (`GROUP BY`/`COUNT`), nunca cargando cada fila a
  Python. Devuelve: entidades por bucket de confianza (low `<0.4` / medium `<0.7` / high `>=0.7`),
  entidades por tipo, claims por fuente, claims por status, `pending_questions` abiertas por target
  (solo `status=OPEN`), y entidades fusionadas (`relation_type="same_as"`) creadas dentro de la
  ventana (`merged_window_hours`, default 24h).
- [x] `GET /knowledge/status` (`app/api/routers/knowledge.py` + `app/api/schemas/knowledge.py`,
  registrado en `app/main.py`) — mismo patrón que `GET /sync/status`: `X-User-Id` /
  `get_current_user_id`, `merged_window_hours` como query param opcional (`ge=1, le=720`).
- [x] Es el chequeo concreto de que "la fuente de conocimiento se pone cada vez más sólida" — ahora
  es una afirmación verificable, no una aspiración.
- [x] Tests: `tests/integration/test_knowledge_stats.py` — cubre base vacía, buckets de confianza,
  claims por fuente/status, filtrado de preguntas resueltas, ventana de merges recientes (incluye
  caso `merged_window_hours=0` para confirmar que excluye hasta los links recién creados), scoping
  por `user_id`, y el endpoint HTTP con y sin el query param.

**Complejidad**: baja — confirmado, sin sorpresas de diseño.

### Phase 8 — Scheduler: backfill automático + ciclos periódicos ✅
- [x] Motivación: hasta esta fase, `run_domain_agent`/`run_rd_domain_agent`/`run_reconciliation`
  solo se disparaban a mano vía `scripts/`. Como `knowledge_processed_documents` arranca vacía, la
  primera corrida de cada agente encuentra **todo el historial ya ingerido** como "no procesado" —
  no hace falta una migración de datos separada — pero sin nada que dispare corridas periódicas,
  ese backfill nunca pasaba de una corrida manual de `batch_size` documentos.
- [x] `app/services/agent/knowledge/scheduler.py`: `KnowledgeAgentScheduler` — mismo patrón que
  `SyncScheduler` (APScheduler opcional, un job por usuario). Un job por `user_id` con al menos una
  integración activa, con intervalo `knowledge_agent_interval_minutes` (default 60m, mínimo 5m
  forzado). Cada ciclo (`_run_cycle`): todas las fuentes respaldadas por `documents`
  (`run_domain_agent` con `knowledge_agent_batch_size`, default 20), después el agente de I+D si
  `id_brain_mcp_url` está configurado, después `run_reconciliation` — cada paso con su propia
  `AsyncSession` y su propio commit, así que una fuente fallando no bloquea ni revierte las demás.
- [x] Backfill de un backlog grande ocurre en varios ciclos (una porción de `batch_size` por fuente
  por ciclo), no en una ráfaga — acota costo/latencia por ciclo a cambio de un backfill inicial más
  lento para cuentas con mucho historial.
- [x] **Explícitamente opt-in** (`enable_knowledge_agents`, default `False`) — a diferencia de
  `SyncScheduler`, NO se activa solo por `is_production`: cada ciclo hace llamadas reales a LLMs
  encima del costo de ingesta ya existente.
- [x] `app/main.py`: arranque/apagado del scheduler en el lifespan, igual que `sync_scheduler`.
- [x] `GET /knowledge/status` ahora también expone `scheduler_active` y `next_scheduled_run` (mismo
  patrón que `GET /sync/status`).
- [x] Tests: `tests/unit/test_knowledge_scheduler.py` — ciclo de vida, intervalo mínimo, carga de
  jobs por usuario, corrida completa del ciclo (incluye skip de `rd` sin configurar, y que una
  fuente fallando con `RuntimeError` no bloquea las demás ni la reconciliación).

**Complejidad**: media — reutiliza `SyncScheduler` como plantilla; lo nuevo fue encadenar múltiples
pasos con aislamiento de fallas por paso en vez de por integración.

---

## Riesgos a vigilar

- **Costo**: 6 agentes de dominio + swarms de reconciliación corriendo por ciclo de sync pueden
  sumar bastante LLM spend. El pre-filtro determinístico de Phase 4 es lo que lo mantiene manejable
  — no es opcional, es la única razón por la que esto no explota en costo. Como además `ask_peer_agents`
  (Phase 1) puede disparar el mismo swarm proactivamente ante cualquier duda de un agente, hace
  falta un umbral explícito (ej: solo si `consult_knowledge_base` no devolvió nada Y hay un par
  plausible) para que un agente no dispare un swarm por cada documento ambiguo que procesa.
- **Loops de swarm sin convergencia**: `Swarm` tiene `max_handoffs` — hay que fijar un límite
  conservador y que el timeout se resuelva SIEMPRE en `pending_questions`, nunca en silencio.
- **Contaminación cruzada de usuarios**: todo el esquema nuevo debe estar scoped por `user_id`
  igual que el resto del sistema — un `entity_link` jamás puede cruzar usuarios.
- **No pisar la integración de Notion existente** (Phase 3) — el agente de dominio de Notion es
  consumidor, no productor, del lado de `app/services/notion/`.

---

## Orden y checkpoints

Fase 0 → 1 → code review → 2 → 3 → 4 → code review (foco costo/convergencia) → 5 → 7 → 6 (cuando
haya datos del MCP). Cross-check contra `specs/qa-plan.md` después de cada fase, como en el resto
del proyecto.
