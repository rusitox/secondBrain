# Plan: Migración del orquestador multi-agente a AWS Strands Agents

## Goal

Reemplazar el orquestador multi-agente custom de `app/services/agent/` por AWS Strands Agents,
eliminando el boilerplate de JSON schemas + tool_executors manuales y habilitando acceso dinámico
a built-in tools (datetime, web search, http_request).

---

## Scope

- **IN**: Reescritura de `orchestrator.py`, `agent.py` (shim), `tool_definitions.py`, y todos los
  archivos bajo `app/services/agent/tools/`. Adaptación del router `app/api/routers/agent.py`
  para SSE compatible con Strands. Wrapper de sesión/contexto para el agente Strands.
- **OUT**: `app/services/connectors/`, `app/services/ingestion/`, `app/services/retrieval/`,
  `app/models/`, `cli/`, `static/voice/`, `app/services/notion/`, `app/services/briefing/`,
  `app/services/sync/`. Los tests de tools individuales deben seguir pasando (se adaptan, no se eliminan).

---

## Inventario: qué cambia vs qué se preserva

| Archivo / Módulo | Estado | Motivo |
|---|---|---|
| `app/services/agent/orchestrator.py` | **Reemplazado** | Core del cambio: `MultiAgentOrchestrator` → Strands `Agent` + sub-agents |
| `app/services/agent/agent.py` | **Reemplazado** | Shim de compatibilidad se actualiza para delegar a nuevo Strands orchestrator |
| `app/services/agent/tool_definitions.py` | **Eliminado** | Strands infiere schemas de type hints con `@tool` |
| `app/services/agent/tools/memory_retriever.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/task_manager.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/calendar_sync.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/style_analyzer.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/save_learning.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/search_learnings.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/services/agent/tools/sync_status.py` | **Adaptado** | Clase → función decorada con `@tool` |
| `app/api/routers/agent.py` | **Adaptado** | SSE + session management se rewirean al nuevo orchestrator |
| `app/services/llm/claude_client.py` | **Preservado** | Strands usa su propio LLM backend; `LLMClient` sigue usándose en briefing/commitments |
| `app/services/agent/agents/` (base, domain, tasks, cross) | **Eliminados** | Absorbidos por sistema de sub-agents de Strands |
| `requirements.txt` | **Modificado** | Se agrega `strands-agents` y opcionalmente `strands-agents-tools` |
| `tests/unit/test_agent.py` | **Adaptado** | Se ajustan los mocks; los invariantes de contrato (`answer`, `session_id`, `sources`, `tools_used`) permanecen |
| Todo lo demás | **Sin cambios** | Ver Scope OUT |

---

## Análisis de Strands

### Modelo conceptual de Strands

Strands Agents (`strands-agents`) es un framework de AWS que provee:

1. **`@tool` decorator**: convierte una función Python async en una tool con schema JSON autogenerado
   desde type hints y docstrings. Elimina el mantenimiento de `AGENT_TOOLS` JSON manual.

2. **`Agent` class**: orquesta un loop tool-use (similar al actual `generate_with_tools`). Recibe
   una lista de tools, un model ID de Bedrock o Anthropic, y un system prompt.

3. **Built-in tools** (vía `strands-agents-tools`):
   - `current_time` → reemplaza el prefijo manual de fecha en los prompts
   - `http_request` → habilita llamadas HTTP directas desde sub-agents (útil para webhooks, APIs externas)
   - `use_aws` → para integraciones AWS futuras (S3, DynamoDB, etc.)
   - `web_search` (si se configura con Brave Search API key) → búsqueda web nativa

4. **Streaming**: Strands provee `agent.stream_async()` que emite eventos `AgentEvent` con tipos
   `text`, `tool_use`, `tool_result`. Esto mapea directamente al SSE del router actual.

5. **Session/context**: Strands no gestiona conversación persistente (sin DB). El historial debe
   inyectarse explícitamente como `messages` al construir el agente por llamada.

### Cómo mapear la arquitectura actual

| Concepto actual | Equivalente Strands |
|---|---|
| `_SubAgent.run()` + `generate_with_tools()` | `Agent(tools=[...]).stream_async(prompt)` |
| `tool_definitions.py` JSON schemas | Type hints + docstrings + `@tool` |
| `_build_tool_executors()` dict | Lista de funciones con `@tool` pasada al `Agent` |
| Paralelismo con `asyncio.gather()` | Se mantiene: un `Agent` Strands por sub-agente, corriendo en paralelo |
| `_synthesize()` con LLM puro | Se mantiene como llamada directa a LLM (sin tools), usando `LLMClient.generate()` |
| `_resolve_session()` + `_persist_turns()` | Se mantiene en el orchestrator wrapper de Strands |
| `stream_callback` en SSE | `async for event in agent.stream_async()` |

### Problema clave: inyección de contexto en tools

Las tools actuales reciben `db: AsyncSession` y `user_id: uuid.UUID` como parámetros de instancia
o closures. Strands `@tool` no acepta parámetros extras fuera del schema JSON (los que el LLM pasa).

**Solución**: usar un **context object** pasado como closure en la construcción de cada tool por llamada.
Cada invocación del orquestador crea funciones `@tool` con `db` y `user_id` capturados en el closure,
y pasa esas funciones al `Agent` Strands. Esto es idéntico al patrón actual de `_build_tool_executors`.

Ejemplo conceptual (no implementación):
```
# Por cada query, se construyen tool functions con db/user_id en closure
def make_search_memory_tool(db, user_id, embedder):
    @tool
    async def search_memory(query: str, source: Optional[str] = None, top_k: int = 5) -> list:
        """Search the user's knowledge base..."""
        ...
    return search_memory
```

### Streaming SSE compatible

El router actual usa una `asyncio.Queue` como bridge entre la coroutine del agente y el
`EventSourceResponse`. Con Strands:

```
async for event in strands_agent.stream_async(prompt):
    if event is AgentEvent del tipo text → emitir "token"
    if event es tool_use → emitir "tool_call"
    if event es tool_result → emitir "tool_result"
```

La `Queue` puede eliminarse; el generador SSE itera directamente sobre `stream_async()`.
Los sub-agents corren en paralelo antes del synthesis; el streaming sólo aplica al paso de synthesis
(igual que hoy).

### Model backend

Strands soporta Anthropic nativo (no requiere Bedrock). Se configura con `AnthropicModel` y la
`anthropic_api_key` existente. No se necesita migrar a Bedrock.

---

## Fases de implementación

### Phase 1: Instalación y spike de compatibilidad

**Objetivo**: verificar que Strands corre en el entorno, que los type hints de Python 3.8 son
compatibles, y que el `@tool` decorator funciona con funciones async que usan closures.

- [ ] Agregar `strands-agents>=0.1` y `strands-agents-tools>=0.1` a `requirements.txt`
- [ ] Verificar compatibilidad Python 3.8: Strands requiere Python 3.10+. Si es así, documentar
  el blocker y evaluar si el VPS puede actualizar Python (el Dockerfile ya usa Python 3.11).
  **Este es el riesgo #1** — ver sección Riesgos.
- [ ] Crear `app/services/agent/strands_spike.py` (archivo temporal) con un `Agent` Strands mínimo
  que use una sola tool `@tool` para validar el patrón de closure. Borrar al finalizar.
- [ ] Confirmar que `AnthropicModel` de Strands puede usar la `LLM_API_KEY` existente sin cambios
  de configuración.

**Complejidad**: baja-media. Blocker potencial en Python 3.8.

---

### Phase 2: Migrar tools individuales a `@tool`

**Objetivo**: convertir las 7 tool classes actuales a funciones decoradas. Sin tocar el orchestrator
todavía.

**Archivo nuevo**: `app/services/agent/strands_tools.py`

Contiene todas las tool factories (funciones que reciben contexto y devuelven funciones `@tool`):

- [ ] `make_search_memory_tool(db, user_id, embedder, source_filter=None)` → `@tool search_memory`
- [ ] `make_list_tasks_tool(db, user_id)` → `@tool list_tasks`
- [ ] `make_get_calendar_tool(db, user_id, user_timezone)` → `@tool get_calendar`
- [ ] `make_save_learning_tool(db, user_id, embedder)` → `@tool save_learning`
- [ ] `make_search_learnings_tool(db, user_id, embedder)` → `@tool search_learnings`
- [ ] `make_get_sync_status_tool(db, user_id)` → `@tool get_sync_status`
- [ ] `make_get_style_tool(db, user_id)` → `@tool get_user_style` (usado solo en synthesis setup)

Las implementaciones internas delegan a las mismas clases Tool actuales
(`MemoryRetrieverTool`, `TaskManagerTool`, etc.) para no duplicar lógica y preservar los tests
unitarios de esas clases.

Archivos `app/services/agent/tools/*.py` se mantienen intactos en esta fase.

**Complejidad**: baja. Solo wrapping.

---

### Phase 3: Reemplazar el orchestrator

**Objetivo**: reemplazar `orchestrator.py` con `StrandsOrchestrator` que preserve la interfaz pública
`query(db, user_id, question, session_id, stream_callback)` y el dict de retorno.

**Archivo**: `app/services/agent/orchestrator.py` (reemplazado in-place para no romper imports)

Estructura interna del nuevo orchestrator:

```
StrandsOrchestrator.query():
  1. _resolve_session()       ← sin cambios, misma lógica SA
  2. _fetch_user_identity()   ← sin cambios
  3. StyleAnalyzerTool.get_style() ← llamada directa, no via tool
  4. _route_sub_agents()      ← devuelve lista de (agent_name, tools_list)
  5. asyncio.gather() de sub-agents:
       para cada sub-agent:
         tools = make_*_tool(db, user_id, ...) × los tools asignados
         agent = Agent(model=AnthropicModel(...), tools=tools, system=sub_prompt)
         result = await agent(augmented_question)  ← Strands no-streaming
  6. _synthesize() via LLMClient.generate()  ← sin cambios
  7. _persist_turns()         ← sin cambios
  8. Retornar dict con answer, tools_used, sources, session_id, iterations
```

Nota sobre `tools_used` e `iterations`: Strands `AgentResult` expone métricas de tool use.
Se mapean al mismo formato de retorno actual.

- [ ] Implementar `StrandsOrchestrator` en `orchestrator.py` preservando la firma pública
- [ ] `_route_sub_agents()` retorna la misma lógica de keywords que `_route_agents()` actual
- [ ] Cada sub-agent Strands recibe solo sus tools (igual que hoy): Slack → solo `search_memory`,
  Tasks → `list_tasks + get_calendar + search_learnings + save_learning`, etc.
- [ ] Mantener `SubAgentResult` como dataclass de resultado intermedio (o equivalente)
- [ ] El sistema prompt de cada sub-agent se mantiene igual (strings `_SLACK_SYSTEM`, etc.)

**Complejidad**: media-alta. Es el núcleo del cambio.

---

### Phase 4: Actualizar el shim `agent.py` y el router

**Objetivo**: `AgentOrchestrator.query()` delega al nuevo `StrandsOrchestrator`. El router SSE
usa `stream_async()` de Strands.

- [ ] `app/services/agent/agent.py`: `AgentOrchestrator.query()` instancia `StrandsOrchestrator`
  (era `MultiAgentOrchestrator`). Sin cambios en la firma del método.
- [ ] `app/api/routers/agent.py` endpoint `/agent/query`: sin cambios (ya delega via `agent.py`).
- [ ] `app/api/routers/agent.py` endpoint `/agent/stream`: reemplazar la `asyncio.Queue` bridge por
  iteración directa sobre `strands_agent.stream_async()` solo en el paso de synthesis.
  Los sub-agents corren sin streaming (igual que hoy); solo el synthesis final es streamed.
- [ ] Eliminar `tool_definitions.py` o convertirlo en re-exports vacíos si algún import externo lo usa.
  Verificar con grep antes de eliminar.

**Complejidad**: baja (shim), media (SSE rewrite).

---

### Phase 5: Agregar built-in tools opcionales

**Objetivo**: habilitar las built-in tools de Strands que aportan valor real.

- [ ] `current_time` (built-in): reemplazar el prefijo manual `[FECHA DE HOY: {today_str}]`
  en el `augmented_question`. El sub-agent llama a `current_time` cuando necesita la fecha.
  Agregar al tool set de cada sub-agent que lo necesite (Tasks, CrossKnowledge).
- [ ] `http_request` (built-in, opcional): agregar al `CrossKnowledgeAgent` para permitir
  llamadas a APIs externas desde el agente. Requiere evaluación de riesgos de seguridad
  (prompt injection vía URLs maliciosas en documentos). Proteger con allowlist de dominios.
- [ ] `web_search` (built-in, requiere Brave Search API key): agregar nueva config key
  `BRAVE_SEARCH_API_KEY` en `app/core/config.py`. Solo habilitar si la key está presente.
  Agregar al `CrossKnowledgeAgent` como tool opcional.
- [ ] Actualizar `app/core/config.py` con `brave_search_api_key: Optional[str] = None`

**Complejidad**: baja. Configuración, no lógica.

---

### Phase 6: Adaptar tests y cleanup

**Objetivo**: tests pasan con el nuevo sistema. Eliminar código muerto.

- [ ] `tests/unit/test_agent.py`: los tests de tools individuales (`TestMemoryRetrieverTool`, etc.)
  no cambian porque las clases Tool se mantienen. Los tests de `TestAgentOrchestrator` se
  rewirean para mockear el `Agent` de Strands en lugar de `LLMClient.generate_with_tools`.
- [ ] Verificar que `AGENT_SYSTEM_PROMPT` sigue exportado desde `agent.py` (lo usan los tests).
- [ ] Eliminar `app/services/agent/tool_definitions.py` si no hay imports externos.
- [ ] Eliminar archivos `app/services/agent/agents/` (base, domain, tasks, cross) si fueron
  absorbidos. Verificar que ningún import los referencia.
- [ ] Correr `mypy app/ cli/ --ignore-missing-imports` y resolver errores.
- [ ] Correr `pytest tests/` y verificar que todos pasan.

**Complejidad**: media. El riesgo es el cambio de interfaz para mockear.

---

## Riesgos y mitigaciones

### Riesgo 1 (CRÍTICO): Compatibilidad Python 3.8

**Problema**: `strands-agents` requiere Python 3.10+. La codebase usa Python 3.8+ como target
mínimo (según CLAUDE.md y la memoria del proyecto sobre feedback de Python 3.8 compat).

**Impacto**: si el entorno de desarrollo local o el CI usa Python 3.8/3.9, el package no instala.

**Mitigación**: el `Dockerfile` usa Python 3.11 (multi-stage build), y el VPS corre con esa imagen.
El riesgo real es solo en development local si alguien corre Python 3.8. Opciones:
  - Documentar Python 3.10+ como nuevo mínimo en `pyproject.toml` y `CLAUDE.md`.
  - Agregar `python_requires=">=3.10"` en `pyproject.toml`.
  - Verificar en Phase 1 qué versión corre en el Mac de desarrollo y en CI.

### Riesgo 2 (ALTO): Cambio de interfaz para tool injection

**Problema**: Strands `@tool` no acepta parámetros de contexto (db, user_id). El patrón de
closure resuelve esto pero agrega complejidad y requiere que cada tool sea instanciada por query.

**Impacto**: posible overhead de instanciación por request (minor); complejidad de testing (los
mocks deben capturar las funciones generadas en los closures).

**Mitigación**: el patrón ya existe en el código actual (`_build_tool_executors` hace exactamente
esto). No es nuevo territorio.

### Riesgo 3 (ALTO): Streaming SSE con Strands

**Problema**: el protocolo de eventos SSE actual (`tool_call`, `tool_result`, `token`, `done`,
`error`) fue diseñado para el loop manual de `generate_with_tools`. Strands emite `AgentEvent`
con su propia taxonomía de tipos.

**Impacto**: si el CLI o la voice UI parsean los tipos de eventos SSE directamente, un cambio
de nombre rompe el cliente.

**Mitigación**: el router debe hacer la traducción explícita de `AgentEvent` → eventos SSE con
los mismos nombres que hoy. No exponer los tipos internos de Strands al wire protocol.

### Riesgo 4 (MEDIO): Paralelismo de sub-agents con Strands

**Problema**: el `Agent` de Strands es una clase diseñada para un solo flujo. Correr 7 instancias
en `asyncio.gather()` no ha sido probado con la versión actual del framework.

**Impacto**: posibles race conditions o problemas de thread-safety en el client de Strands.

**Mitigación**: revisar la documentación de Strands sobre concurrencia antes de Phase 3.
Si hay problemas, los sub-agents pueden correr secuencialmente con latencia aceptable (max ~7
llamadas LLM en secuencia vs. paralelas). Los tests de carga ayudan a detectar esto.

### Riesgo 5 (MEDIO): `tools_used` e `iterations` en el response dict

**Problema**: el contrato de retorno actual incluye `tools_used` (lista de nombres de tools usadas)
e `iterations` (count de rondas LLM). Los tests verifican estos campos explícitamente.

**Impacto**: si Strands no expone métricas equivalentes, los tests fallan.

**Mitigación**: Strands expone el historial de tool calls en `AgentResult`. Se puede extraer
`tools_used` e `iterations` del result object. Verificar la API exacta en Phase 1.

### Riesgo 6 (BAJO): `web_search` con prompt injection

**Problema**: si el `CrossKnowledgeAgent` puede hacer `web_search`, un documento ingresado
malicioso podría contener URLs o instrucciones para que el agente busque contenido adversario.

**Mitigación**: el system prompt ya incluye protección de prompt injection ("UNTRUSTED content").
Adicionalmente, la tool `web_search` debe tener una allowlist de dominios en Phase 5.
La web search es opcional y solo se habilita si `BRAVE_SEARCH_API_KEY` está configurada.

---

## Archivos a modificar / crear

| Acción | Archivo |
|---|---|
| Crear | `app/services/agent/strands_tools.py` |
| Reemplazar | `app/services/agent/orchestrator.py` |
| Reemplazar | `app/services/agent/agent.py` |
| Adaptar | `app/api/routers/agent.py` |
| Adaptar | `tests/unit/test_agent.py` |
| Modificar | `requirements.txt` |
| Modificar | `app/core/config.py` (nueva key `brave_search_api_key`) |
| Eliminar (Phase 6) | `app/services/agent/tool_definitions.py` |
| Preservar intactos | `app/services/agent/tools/*.py` (las clases Tool) |
| Preservar intactos | Todos los archivos en Scope OUT |

---

## Dependencies a agregar

```
# requirements.txt — agregar bajo sección AI
strands-agents>=0.1,<1.0
strands-agents-tools>=0.1,<1.0   # para built-in tools (current_time, http_request, web_search)
```

Verificar la versión exacta disponible en PyPI al momento de implementar.
El package `anthropic>=0.30` ya está presente y es compatible con el backend de Strands.

---

## Orden de implementación recomendado

```
Phase 1 (spike) → Phase 2 (tools) → Phase 3 (orchestrator) → Phase 4 (router/shim)
→ [code review] → Phase 5 (built-ins) → Phase 6 (tests/cleanup) → [QA]
```

El code review entre Phase 4 y Phase 5 es el punto de control crítico: en ese punto el sistema
debe ser funcionalmente equivalente al actual. Phase 5 agrega capacidades nuevas y puede
postergarse si hay riesgos de seguridad pendientes de resolver.
