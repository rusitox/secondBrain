# Plan: Sistema multi-agente de conocimiento unificado

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

### Phase 0 — Esquema base
- [ ] Migración Alembic: `entities`, `entity_claims`, `entity_links`, `pending_questions`.
- [ ] Modelos SQLAlchemy en `app/models/` (siguiendo `UUIDMixin`/`TimestampMixin` existentes).
- [ ] Sin lógica de agentes todavía — solo esquema + CRUD helpers + tests de modelo.

**Complejidad**: baja. Prerequisito de todo lo demás.

### Phase 1 — Agente de dominio: implementación de referencia (Slack)
- [ ] `app/services/agent/knowledge/domain_agent.py`: factory `make_domain_agent(source, ...)` —
  un Strands `Agent` cuyo mandato es leer `Document` rows nuevos de esa fuente, proponer
  entidades/claims a la Capa 3, autoevaluar su confianza, y recorrer la escalera de resolución
  (consultar conocimiento existente → consultar pares vía swarm si hay uno plausible → validar con
  el humano con una candidata → escalada en blanco) cuando algo no le cierra, sin necesidad de que
  sea un conflicto cruzado — puede dudar de algo puramente dentro de su propia fuente.
- [ ] Tools propios: `propose_entity`, `propose_claim`, `consult_knowledge_base`,
  `ask_peer_agents` (dispara el swarm acotado), `escalate_or_validate`, `get_unprocessed_documents`.
- [ ] Implementación completa + tests para Slack como referencia.
- [ ] Disparo manual (CLI o endpoint) para poder probarlo antes de engancharlo al scheduler.

**Complejidad**: alta — es el patrón que todo lo demás reutiliza. Vale la pena un code review
completo acá antes de replicar.

### Phase 2 — Réplica a Outlook, Teams, Fathom ✅
- [x] Reusar la factory de Phase 1; ajustar el prompt de extracción por fuente (ej: Outlook tiene
  eventos de calendario además de emails; Fathom son transcripciones de reuniones más largas).
- [x] Tests por fuente.

**Complejidad**: media — mecánica, no de diseño.

### Phase 3 — Notion
- [ ] Fase separada porque `app/services/notion/` ya tiene sync bidireccional y publisher propios.
  El agente de dominio acá es de **solo lectura** hacia la Capa 3 — no debe escribir de vuelta a
  Notion ni interferir con `NotionSync`.

**Complejidad**: media, con cuidado de no pisar la integración existente.

### Phase 4 — Motor de reconciliación
- [ ] Pre-filtro determinístico: email exacto, nombre exacto, similaridad de embedding sobre umbral
  → auto-link como `same_as` sin gastar LLM.
- [ ] Zona ambigua → mismo `Swarm` acotado que usa `ask_peer_agents` (Phase 1) — la reconciliación
  es la invocación *reactiva* (por lote, detectando candidatos) del mismo mecanismo que un agente
  dispara *proactivamente* cuando tiene una duda propia. Un solo código de negociación, dos gatillos.
- [ ] Sin consenso (swarm no converge) → `pending_questions` con `target=human` y
  `candidate_answer` si el swarm llegó a algo parcial, nunca una pregunta en blanco si evitable.
- [ ] Recalcular `entities.confidence` según corroboración.
- [ ] Disparo: después de que terminan los agentes de dominio de un ciclo de sync.

**Complejidad**: alta — es el corazón de "los agentes se ponen de acuerdo entre ellos". Code review
obligatorio, con foco en costo (cuántos swarms se disparan por ciclo) y en que el pre-filtro
determinístico realmente reduce el volumen antes de gastar LLM.

### Phase 5 — Orquestador: lectura + feedback loop
- [ ] Tool `query_knowledge(entity_or_topic)` en `strands_tools.py`.
- [ ] El orquestador surge `pending_questions` abiertas en la conversación cuando es relevante.
- [ ] La respuesta del usuario se escribe como `entity_claims` con `asserted_by_agent="user"` y
  `status=confirmed_by_user`, sube la confianza de la entidad, y cierra la `pending_question`.

**Complejidad**: media.

### Phase 6 — Agente de I+D (plataforma propia vía MCP)
- [ ] Diferido hasta tener los datos de conexión del MCP (decisión explícita del usuario).
- [ ] Mismo patrón de Phase 1, pero `get_unprocessed_documents` consulta el MCP en vez de la tabla
  `documents`.

**Complejidad**: por definir — depende de las capabilities que exponga ese MCP.

### Phase 7 — Observabilidad de solidez
- [ ] Vista/endpoint (estilo `get_sync_status`) con: entidades por bucket de confianza, claims por
  fuente, `pending_questions` abiertas, entidades fusionadas en el último ciclo.
- [ ] Es el chequeo concreto de que "la fuente de conocimiento se pone cada vez más sólida" — sin
  esto la afirmación no es verificable.

**Complejidad**: baja.

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
