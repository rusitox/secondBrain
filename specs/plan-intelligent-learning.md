# Plan: Intelligent Learning Agent

## Goal
Evolucionar el agente de secondBrain de un sistema reactivo-reportador a uno que aprende activamente: relaciona contenido cross-platform, detecta ownership de compromisos con incertidumbre explícita, y usa el welcome para aprender en lugar de reportar.

---

## Decisiones de diseño

### Lo que se hace

1. **Todo el aprendizaje de ownership pasa por la tabla `memories` existente** — no se agrega `confidence` ni `needs_confirmation` al modelo `Commitment`. El razonamiento: los compromisos son hechos crudos detectados del texto; el ownership resuelto es un insight aprendido. Separar los layers evita contaminar el modelo de datos con estado mutable de baja confianza.

2. **No se crea un tool `correlate_topics`** — se mejora el system prompt para que el agente use `search_memory` con múltiples queries estratégicas. Un tool extra agrega complejidad sin beneficio real: el LLM ya puede encadenar búsquedas. Lo que falta es la instrucción explícita de hacerlo.

3. **El `LearningExtractor` post-ingestion se activa y se amplía** — hoy existe el código pero no está conectado al pipeline de ingestion. Se conecta y se añaden dos extractores especializados en ownership (quién habla de qué proyectos, quién asigna tareas a quién).

4. **El welcome cambia de "reportar todo" a "elegir una incógnita y preguntar"** — el agente al inicio selecciona el commitment de mayor incertidumbre de ownership (owner = "unknown" o "speaker") y formula una pregunta concreta. La respuesta del usuario se persiste como learning.

5. **El agente nunca asume — siempre pregunta, una sola vez** — el system prompt exige preguntar antes de asumir, y buscar en learnings para no repetir la misma pregunta.

### Lo que NO se hace

- No se agrega `confidence_score` al modelo `Commitment` — agrega complejidad de schema sin valor directo; el agente resuelve la incertidumbre via learnings.
- No se crea ningún endpoint nuevo de API — todo pasa por `/agent/query` existente.
- No se modifica el modelo `Memory` — el schema actual (`content`, `entities`, `importance`, `source_type`, `source_ref`, `embedding`) es suficiente para almacenar ownership learnings.
- No se procesa el historial completo de commitments para re-evaluar ownership — solo los nuevos documentos ingresados y los que el agente encuentra durante la conversación.

---

## Scope

**IN:**
- Modificaciones al `AGENT_SYSTEM_PROMPT` (eje 1, 3)
- Modificación al `_WELCOME_PROMPT` en `cli/chat.py` (eje 5)
- Ampliación de `EXTRACTION_INSTRUCTIONS` en `LearningExtractor` (eje 4)
- Conexión del `LearningExtractor` al `IngestionPipeline` (eje 4)
- Mejora del prompt de detección de commitments para marcar ownership ambiguo (eje 2)

**OUT:**
- Cambios de schema en base de datos
- Nuevos tools de agente
- Nuevos endpoints de API
- Interfaz de UI para revisar learnings
- Re-procesamiento retroactivo de compromisos existentes

---

## Phase 1 — Ownership questioning via system prompt (sin DB changes, máximo impacto inmediato)

**Objetivo:** El agente pregunta en lugar de asumir cuando detecta ownership ambiguo.

**Archivos a modificar:**
- `app/services/agent/agent.py` — `AGENT_SYSTEM_PROMPT`

**Qué cambia:**
Agregar una sección nueva al system prompt llamada `Ownership resolution protocol` con estas reglas explícitas:

1. Cuando una tarea tiene `owner = "unknown"`, `owner = "speaker"`, o cualquier pronombre vago ("I", "yo", "nosotros", "we"), el agente NO asume que es de Mariano. En cambio, busca en `search_learnings` con query `"ownership [nombre del proyecto/contexto]"` para ver si ya sabe la respuesta.

2. Si no encuentra un learning previo que resuelva el ownership, formula **una sola pregunta concreta** al usuario: `"El compromiso X fue detectado como owner='speaker' en [fuente]. ¿Es tuyo o de otra persona?"`.

3. Cuando el usuario responde, el agente llama a `save_learning` inmediatamente con el formato canónico: `"El compromiso '[texto]' en el contexto de [proyecto/fuente] es de [persona]. Detectado el [fecha]."` con entities apropiadas y `importance=4`.

4. En queries futuras que involucren ese proyecto o persona, el agente busca learnings de ownership primero antes de presentar tareas.

**Qué NO cambia:** tool_definitions.py, modelos, DB, CLI.

**Complejidad:** Baja — solo cambios de texto en el prompt.

**Riesgo:** El agente puede volverse muy verboso haciendo preguntas en cascada. Mitigación: la regla debe ser "una sola pregunta por turno, máximo una por sesión de welcome".

---

## Phase 2 — Welcome redesign: de reporte a aprendizaje

**Objetivo:** El inicio no vuelca todo lo pendiente — selecciona la incógnita más relevante y pregunta.

**Archivos a modificar:**
- `cli/chat.py` — `_WELCOME_PROMPT`

**Qué cambia:**
Reemplazar el `_WELCOME_PROMPT` actual (que pide: tasks + calendar + memory + resumen completo) por uno que instruye al agente a:

1. Llamar a `get_user_style`.
2. Llamar a `search_learnings` con queries sobre ownership pendiente: `"ownership desconocido"`, `"owner unknown"`, `"compromisos sin dueño claro"`.
3. Llamar a `list_tasks` pero con foco selectivo: buscar los items con `owner = "unknown"` o `owner = "speaker"`.
4. Llamar a `search_memory` para contexto reciente solo de los items de alta incertidumbre encontrados.
5. Llamar a `get_calendar` para mencionar brevemente las reuniones del día.

Con toda esa información, construir un saludo que:
- Salude brevemente y con calidez (2-3 líneas máximo).
- Presente **una sola pregunta de ownership** sobre el item de mayor incertidumbre e impacto.
- Mencione las reuniones del día en una línea.
- No liste todas las tareas pendientes — eso está disponible bajo demanda con `/commitments`.

**Formato esperado de la respuesta del agente:**
```
¡Buenos días, Mariano! [algo concreto del contexto reciente]

Antes de arrancar, necesito aclarar algo: detecté que "[texto del commitment]" 
fue asignado como owner desconocido en [fuente] del [fecha]. ¿Es tuyo o de 
[persona mencionada en el contexto]?

Hoy tenés [N] reuniones — la primera es [nombre] a las [hora].
```

**Qué NO cambia:** `_show_static_welcome`, la lógica de fallback, ningún archivo backend.

**Complejidad:** Baja.

**Riesgo:** Si no hay commitments con owner ambiguo, el agente no tiene pregunta que hacer. El prompt debe incluir un fallback: si no hay incógnitas de ownership, hacer una pregunta de aprendizaje general ("¿Hay algo nuevo en el proyecto X que deba saber?").

---

## Phase 3 — LearningExtractor: conectar al pipeline + ampliar foco en ownership

**Objetivo:** Cada vez que se ingesta contenido nuevo, el sistema extrae automáticamente learnings de ownership sin intervención del usuario.

### Parte A — Conectar LearningExtractor al pipeline

**Archivos a modificar:**
- `app/services/ingestion/pipeline.py` — `IngestionPipeline.__init__` y `ingest_raw`
- Cualquier lugar donde se construye `IngestionPipeline` (buscar en routers de ingestion y sync scheduler)

**Qué cambia:**
`IngestionPipeline` acepta un tercer parámetro opcional `learning_extractor: Optional[LearningExtractor]`. Al final de `ingest_raw`, después del step 5 (commitment detection), si `self._learning_extractor` está definido y se crearon documentos nuevos, se llama a `learning_extractor.extract_from_documents(db, user_id, [documentos nuevos])`.

La construcción de `IngestionPipeline` en los routers/scheduler debe instanciar y pasar el `LearningExtractor`. Buscar en `app/api/routers/ingestion.py` y `app/services/sync/scheduler.py` los puntos de construcción.

**Complejidad:** Media — requiere identificar todos los puntos de construcción del pipeline y inyectar la dependencia.

### Parte B — Ampliar EXTRACTION_INSTRUCTIONS para ownership

**Archivos a modificar:**
- `app/services/agent/learning_extractor.py` — `EXTRACTION_INSTRUCTIONS`

**Qué cambia:**
Agregar al prompt de extracción un foco explícito en:

- **Quién habla / quién asigna:** Cuando el autor del documento (campo `author` en metadata) menciona que otra persona hará algo, extraer: `"[Autor] asignó a [persona] la tarea de [X] en el contexto de [fuente]"`.
- **Proyectos mencionados por el usuario:** Si el author es Mariano Ortega o mariano.ortega@gmail.com, extraer learnings de mayor importancia (5) sobre los proyectos que menciona como propios.
- **Ownership explícito:** Si alguien dice "eso lo hace Mariano" o "eso te toca a vos" dirigido a Mariano, extraer como ownership confirmado con importance=5.

El formato de entities debe incluir `source_author` como campo adicional cuando es relevante.

**Complejidad:** Baja — solo texto del prompt.

---

## Phase 4 — Commitment detector: marcar ambigüedad de ownership

**Objetivo:** El detector de compromisos emite una señal de confianza de ownership que el agente puede usar como trigger para preguntar.

**Archivos a modificar:**
- `app/services/commitments/prompts.py` — `COMMITMENT_DETECTION_PROMPT`
- `app/services/commitments/detector.py` — `DetectedCommitment` dataclass y `_parse_response`

**Qué cambia:**

En `COMMITMENT_DETECTION_PROMPT`: agregar un campo opcional `"owner_confidence"` a la respuesta JSON:
- `"high"`: el owner es explícito y nombrado (ej: "Juan dijo que va a...").
- `"low"`: el owner es inferido de contexto o es un pronombre ("I", "yo", "nosotros", "speaker", "the team").
- `"unknown"`: no hay owner identificable.

En `DetectedCommitment`: agregar campo `owner_confidence: str = "unknown"`.

En `_parse_response`: mapear el nuevo campo.

En el `Commitment` model: **no se agrega ningún campo nuevo** — el `owner_confidence` se usa solo en la detección para decidir qué commitments el agente debe priorizar al preguntar. La información ya está implícita en el valor del campo `owner` (si es "unknown" o "speaker", la confianza es baja).

Alternativa más simple (recomendada): en lugar de agregar `owner_confidence`, mejorar el prompt para que cuando el owner sea incierto, el detector escriba literalmente `"owner": "ambiguous:[razón]"` — por ejemplo `"owner": "ambiguous:pronoun-yo"` o `"owner": "ambiguous:no-subject"`. Esto permite al agente filtrar por `owner` que empieza con `"ambiguous:"` sin cambios de schema.

**Complejidad:** Baja-media.

**Riesgo:** El detector ya usa `owner = "unknown"` como fallback. La mejora es incremental — el agente de Phase 1 ya puede operar sobre `owner = "unknown"` sin este cambio. Esta phase refina la señal.

---

## Phase 5 — Cross-platform topic correlation via system prompt

**Objetivo:** El agente correlaciona activamente temas a través de plataformas sin un tool adicional.

**Archivos a modificar:**
- `app/services/agent/agent.py` — `AGENT_SYSTEM_PROMPT`
- `app/services/agent/tool_definitions.py` — descripción de `search_memory`

**Qué cambia:**

En el system prompt, agregar una sección `Cross-platform correlation`:
> Cuando el usuario pregunta sobre un tema, proyecto, o persona, NO hagas una sola búsqueda. Ejecuta search_memory con al menos 3 queries diferentes cubriendo distintas plataformas y ángulos del mismo tema. Ejemplo para "proyecto Alpha": busca "Alpha Slack", "Alpha reunión", "Alpha email cliente", "deadline Alpha". Luego sintetiza los patrones que emergen del cruce de fuentes.

En la descripción del tool `search_memory`:
> Usar múltiples llamadas con queries distintas para correlacionar el mismo tema a través de plataformas. Cada llamada puede usar el parámetro `source` para filtrar por plataforma específica.

**Por qué no un tool `correlate_topics`:** El LLM ya puede hacer esto con el tool existente si se le instruye explícitamente. Un tool adicional duplicaría funcionalidad y agregaría tokens innecesarios al context de la API.

**Complejidad:** Muy baja — solo texto de prompt y descripción de tool.

---

## Orden de implementación recomendado (por impacto/esfuerzo)

| Fase | Impacto | Esfuerzo | Depende de |
|------|---------|---------|------------|
| Phase 1 — Ownership questioning (prompt) | Alto | Muy bajo | Nada |
| Phase 2 — Welcome redesign | Alto | Muy bajo | Phase 1 recomendable antes |
| Phase 5 — Cross-platform correlation (prompt) | Medio-alto | Muy bajo | Nada |
| Phase 3A — Conectar LearningExtractor | Medio | Medio | Nada |
| Phase 3B — Ampliar EXTRACTION_INSTRUCTIONS | Medio | Bajo | Phase 3A |
| Phase 4 — Commitment detector ownership signal | Bajo | Bajo | Phase 1 (que ya usa owner='unknown') |

**Secuencia recomendada:** 1 → 2 → 5 → 3A → 3B → 4

Las primeras tres phases son cambios de texto puro, sin riesgo de regresión, y producen comportamiento observable de inmediato.

---

## Archivos a modificar / crear

### Modificar (existentes)
- `app/services/agent/agent.py` — `AGENT_SYSTEM_PROMPT` (phases 1, 5)
- `app/services/agent/tool_definitions.py` — descripción de `search_memory` (phase 5)
- `cli/chat.py` — `_WELCOME_PROMPT` (phase 2)
- `app/services/agent/learning_extractor.py` — `EXTRACTION_INSTRUCTIONS` (phase 3B)
- `app/services/ingestion/pipeline.py` — constructor + `ingest_raw` (phase 3A)
- `app/services/commitments/prompts.py` — `COMMITMENT_DETECTION_PROMPT` (phase 4)
- `app/services/commitments/detector.py` — `DetectedCommitment` + `_parse_response` (phase 4)
- Routers/scheduler que construyen `IngestionPipeline` — inyectar `LearningExtractor` (phase 3A)

### Crear (nuevos)
- Ninguno

### Migraciones de DB
- Ninguna

---

## Risks & Considerations

**R1 — Verbosidad del agente en questioning**
Si el agente hace preguntas en cada mensaje, la experiencia se degrada. Mitigación: el prompt debe limitar a "una pregunta por turno" y "buscar en learnings antes de preguntar para no repetir".

**R2 — LearningExtractor duplica trabajo del agente**
Si el extractor post-ingestion y el agente ambos generan learnings similares, el dedup por cosine similarity (threshold 0.92) debería absorberlo. Verificar que el threshold es adecuado para learnings de ownership que son semánticamente similares pero con sujetos distintos — podría requerir bajar a 0.85 para ownership facts.

**R3 — Costo de API por múltiples search_memory calls**
Phase 5 pide al menos 3 búsquedas por tema en lugar de 1. Cada llamada al tool es una roundtrip de embedding. Para `text-embedding-3-small` el costo es marginal, pero el tiempo de respuesta puede aumentar notablemente. Mitigación: limitar a "máximo 4 search_memory calls por query" en el prompt.

**R4 — Owner "speaker" es ambiguo por diseño**
El detector no sabe quién es el speaker sin contexto. En emails, el author en metadata puede resolver esto (si author == mariano.ortega@gmail.com → el speaker es Mariano). El `LearningExtractor` puede aprovechar esta información; el agente también puede hacer `search_memory` con `source=outlook` para cruzar con el author del documento fuente. Documentar este patrón en el prompt del extractor.

**R5 — LearningExtractor no está habilitado en producción**
Verificar en el scheduler (`app/services/sync/scheduler.py`) y en los routers de ingestion si `LearningExtractor` se instancia. Actualmente el código existe pero Phase 3A lo conecta explícitamente. Hasta entonces, el extractor no corre.
