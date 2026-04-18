# Spec: Integración Notion — Lectura + Workspace Colaborativo

## Contexto

secondBrain tiene 4 conectores de lectura (Outlook, Teams, Slack, Fathom) y una interfaz CLI. Hasta ahora el sistema solo **consume** datos. Esta feature agrega Notion como fuente de conocimiento **y** como superficie de salida donde el asistente digital publica contenido. Es el primer paso hacia un asistente con autonomía progresiva.

## Objetivo

1. **Leer** el Notion del usuario para ingestar páginas y databases al knowledge base
2. **Escribir** en el Notion del usuario: el asistente mantiene su propio workspace colaborativo donde publica briefings, commitments, meeting prep, y digests
3. Todo **opcional** — no todos usan Notion. Se ofrece durante el onboarding y se puede activar/desactivar después

---

## Diseño de Alto Nivel

```
┌─────────────────────────────────────────────────┐
│              Notion del Usuario                  │
│                                                  │
│  📄 Mis páginas normales                        │
│  📊 Mis databases normales                      │
│        ↓ (lectura)                               │
│        NotionConnector.fetch_items()             │
│                                                  │
│  ─────────────────────────────────────────       │
│                                                  │
│  🤖 secondBrain (página raíz creada por el bot)│
│    ├── 📋 Commitments    (database)             │
│    ├── 📰 Daily Briefings (database)            │
│    ├── 🤝 Meeting Prep   (database)             │
│    └── 📊 Weekly Digest  (páginas)              │
│        ↑ (escritura)                             │
│        NotionPublisher.publish_*()               │
└─────────────────────────────────────────────────┘
```

**Dos módulos separados:**
- `NotionConnector` (lectura) — sigue el patrón `BaseConnector`, ingesta páginas/databases
- `NotionPublisher` (escritura) — publica contenido al workspace del asistente en Notion

---

## 1. NotionConnector (Lectura)

### Qué ingesta

| Contenido | Cómo |
|---|---|
| Páginas | Título + contenido como texto plano (blocks recursivos) |
| Items de databases | Propiedades + contenido de la página |
| Comentarios | Texto del comentario con author y timestamp |

### Implementación

```python
class NotionConnector(BaseConnector):
    """Connector for Notion pages and databases."""

    platform = "notion"

    async def fetch_items(self, access_token, since=None):
        # 1. search() con filtro last_edited_time > since
        # 2. Para cada página: retrieve blocks recursivamente → texto plano
        # 3. Para cada database: query items → propiedades + contenido
        # 4. Retornar ConnectorItems con metadata
```

**Notion API endpoints usados:**
- `POST /v1/search` — buscar páginas/databases modificadas
- `GET /v1/blocks/{id}/children` — obtener contenido de una página (recursivo)
- `GET /v1/databases/{id}/query` — obtener items de una database
- `GET /v1/comments` — obtener comentarios de una página

**Metadata por item:**

```python
metadata = {
    "type": "notion_page" | "notion_database_item" | "notion_comment",
    "title": "Título de la página",
    "author": "Nombre del último editor",
    "timestamp": "last_edited_time",
    "url": "URL de la página en Notion",
    "parent_type": "workspace" | "page" | "database",
    "database_name": "Nombre de la DB (si aplica)",
    "tags": ["tag1", "tag2"],  # De la propiedad Tags/Labels si existe
}
```

**Conversión de bloques a texto:**
Los bloques de Notion son una estructura anidada. Se convierten a texto plano:
- `paragraph`, `heading_*`, `bulleted_list_item`, `numbered_list_item` → texto directo
- `to_do` → `[x]` o `[ ]` + texto
- `code` → fenced code block
- `quote` → prefijo `>`
- `table` → formato tabla
- `child_page`, `child_database` → se ignoran (se fetchean aparte)
- `image`, `file`, `video`, `embed` → se ignoran (MVP text-only)

**Rate limiting:**
Notion API tiene un rate limit de 3 requests/segundo. Implementar throttling con `asyncio.Semaphore(3)` + retry en 429.

**Filtrado:**
El usuario puede elegir qué ingestar durante el onboarding:
- Todo el workspace (default)
- Solo páginas específicas (selección)
- Excluir ciertas páginas/databases

Se persiste la configuración en `CLIConfig.notion_config`.

### Cleaner

Nuevo cleaner `clean_notion()` en `cleaner.py`:
- Remover metadata de bloques (IDs internos, timestamps de cada bloque)
- Normalizar listas anidadas
- Colapsar whitespace excesivo de la conversión de bloques

---

## 2. NotionPublisher (Escritura)

### Workspace del Asistente

Al activar Notion, el asistente crea una **página raíz** en el workspace del usuario:

```
🤖 secondBrain
├── 📋 Commitments        ← database
├── 📰 Daily Briefings    ← database (una entry por día)
├── 🤝 Meeting Prep       ← database (una entry por meeting)
└── 📊 Weekly Digests     ← sub-página con child pages por semana
```

La página raíz y las databases se crean una sola vez. Los IDs se guardan en config para reusar.

### Contenido publicado

#### Commitments Database

| Propiedad | Tipo | Source |
|---|---|---|
| Title | title | `commitment_text` |
| Status | select (Pending/Completed/Cancelled) | `status` |
| Priority | select (P1/P2/P3/P4/P5) | `priority` |
| Due Date | date | `due_date` |
| Owner | rich_text | `owner` |
| Source | select (slack/outlook/teams/fathom) | del documento origen |
| Detected | date | `created_at` |

**Sync bidireccional en commitments:**
- secondBrain → Notion: cuando se detecta un nuevo commitment, se crea una row
- Notion → secondBrain: cuando el usuario cambia Status en Notion (ej: Pending → Completed), el próximo sync lo refleja en la DB

```python
async def sync_commitments(self, db, user_id):
    # 1. Fetch commitments de la DB local
    # 2. Fetch items de la Notion database
    # 3. Diff: nuevos locales → crear en Notion
    # 4. Diff: cambios en Notion → actualizar en local
    # 5. Diff: cambios locales → actualizar en Notion
```

Resolución de conflictos: **last-write-wins** basado en `updated_at` vs `last_edited_time`.

#### Daily Briefings Database

| Propiedad | Tipo |
|---|---|
| Title | title ("Briefing — Apr 18, 2026") |
| Date | date |
| Status | select (Draft/Published) |

Contenido de la página: el briefing completo en bloques de Notion (headings, bullets, callouts para alertas).

**Flujo:**
1. El scheduler genera el briefing (ya existente)
2. `NotionPublisher.publish_briefing(result)` lo convierte a bloques de Notion
3. Crea una nueva entry en la database con el contenido

#### Meeting Prep Database

| Propiedad | Tipo |
|---|---|
| Title | title (nombre del meeting) |
| Date | date |
| Participants | multi_select |
| Status | select (Pending/Prepared/Done) |

Contenido: resumen de las últimas interacciones con los participantes, commitments pendientes con ellos, contexto relevante.

**Trigger:** se genera automáticamente antes de cada meeting (cuando se detecta en el calendar sync). Opcionalmente el usuario puede pedir uno con `/prep Meeting Name`.

#### Weekly Digest

Página generada cada viernes con:
- Resumen de la semana (commitments cumplidos, nuevos, vencidos)
- Métricas (mensajes procesados, queries hechos)
- Highlights (insights más relevantes)
- Plan para la próxima semana (basado en calendar + commitments)

### Implementación

```python
class NotionPublisher:
    """Publishes content to the assistant's Notion workspace."""

    def __init__(self, token: str, config: NotionWorkspaceConfig):
        self._client = AsyncClient(auth=token)  # notion-client
        self._config = config  # IDs de páginas y databases

    async def setup_workspace(self) -> NotionWorkspaceConfig:
        """Create the root page and databases (first-time setup)."""

    async def publish_briefing(self, briefing: BriefingResult) -> str:
        """Publish a daily briefing. Returns the Notion page URL."""

    async def sync_commitments(self, db, user_id) -> SyncResult:
        """Bidirectional sync of commitments."""

    async def publish_meeting_prep(self, meeting, context) -> str:
        """Publish meeting preparation page."""

    async def publish_weekly_digest(self, digest) -> str:
        """Publish weekly digest page."""
```

---

## 3. Onboarding (Opcional)

### Cambios en el flujo de onboarding

Después de conectar plataformas (Step 2), se ofrece Notion como **feature adicional opcional**:

```
━━━ Step 2b/5: Notion Integration (Optional) ━━━

Would you like to connect Notion?

Notion lets me:
  • Read your pages and databases as knowledge source
  • Maintain a shared workspace where I publish:
    - Your commitment tracking board
    - Daily briefings as pages
    - Meeting prep summaries
    - Weekly digests

This is optional — you can enable it later with /notion connect

  [y] Yes, connect Notion
  [n] No, skip for now

> y

I need a Notion Integration Token.

  1. Go to https://www.notion.so/my-integrations
  2. Click "New Integration"
  3. Name it "secondBrain"
  4. Select your workspace
  5. Copy the "Internal Integration Token"

  Then share the pages you want me to read:
  - Open each page/database in Notion
  - Click "..." → "Connect to" → "secondBrain"

Paste your integration token:
> ntn_••••••••••••••••••

Validating... ✓ Connected to Notion!
  Workspace: Mariano's Workspace
  Pages accessible: 47

What should I read from your Notion?
  [1] Everything I have access to (recommended)
  [2] Let me choose specific pages later

> 1

Setting up my workspace in your Notion...
  Creating "secondBrain" page...     ✓
  Creating Commitments database...   ✓
  Creating Briefings database...     ✓
  Creating Meeting Prep database...  ✓

✓ Notion is ready!
  My workspace: https://notion.so/secondBrain-xxxxx

You can view and edit my workspace anytime in Notion.
```

### Config

```python
@dataclass
class NotionConfig:
    enabled: bool = False
    # Workspace IDs (set during setup)
    root_page_id: Optional[str] = None
    commitments_db_id: Optional[str] = None
    briefings_db_id: Optional[str] = None
    meeting_prep_db_id: Optional[str] = None
    # Reading preferences
    read_mode: str = "all"  # "all" | "selected"
    selected_page_ids: List[str] = field(default_factory=list)
    excluded_page_ids: List[str] = field(default_factory=list)
    # Sync
    last_read_sync: Optional[str] = None
    last_write_sync: Optional[str] = None
```

Se agrega a `CLIConfig.notion_config: Optional[NotionConfig]`.

---

## 4. Slash Commands

| Comando | Acción |
|---|---|
| `/notion connect` | Conectar Notion (mismo flujo que onboarding) |
| `/notion disconnect` | Desconectar y dejar de publicar |
| `/notion status` | Mostrar estado: qué se lee, qué se publica, última sync |
| `/notion sync` | Sync manual (lectura + escritura) |
| `/notion workspace` | Abrir el workspace del asistente en el browser |
| `/prep <meeting>` | Generar meeting prep y publicar en Notion |

---

## 5. Integración con Features Existentes

### Background Sync

El `BackgroundSync` existente se extiende:
- Después de sync de plataformas, si Notion está habilitado:
  1. Sync lectura: ingestar páginas modificadas
  2. Sync escritura: sincronizar commitments bidireccional
  3. Si hay briefing nuevo: publicar en Notion

### Briefing Generator

El `BriefingGenerator` se extiende con un hook post-generación:
```python
# En briefing/generator.py, después de generar:
if notion_publisher:
    await notion_publisher.publish_briefing(result)
```

### Commitment Detection

El `CommitmentDetector` se extiende con un hook post-detección:
```python
# En commitments/detector.py, después de guardar:
if notion_publisher:
    await notion_publisher.create_commitment_row(commitment)
```

---

## Archivos a Crear/Modificar

### Nuevos

| Archivo | Descripción |
|---|---|
| `app/services/connectors/notion.py` | `NotionConnector` — lectura de páginas/databases |
| `app/services/notion/__init__.py` | Package para Notion publisher |
| `app/services/notion/publisher.py` | `NotionPublisher` — escritura al workspace del asistente |
| `app/services/notion/blocks.py` | Conversión bidireccional: contenido ↔ bloques de Notion |
| `app/services/notion/sync.py` | `NotionSync` — sync bidireccional de commitments |
| `app/services/notion/config.py` | `NotionWorkspaceConfig` dataclass |
| `cli/notion_setup.py` | Flujo de setup de Notion en el CLI (onboarding + /notion) |
| `tests/unit/test_notion_connector.py` | Tests del conector |
| `tests/unit/test_notion_publisher.py` | Tests del publisher |
| `tests/unit/test_notion_blocks.py` | Tests de conversión de bloques |
| `tests/unit/test_notion_sync.py` | Tests del sync bidireccional |
| `tests/integration/test_notion_connector.py` | Tests de integración (HTTP mocked) |
| `tests/integration/test_notion_publisher.py` | Tests de integración del publisher |

### Modificar

| Archivo | Cambios |
|---|---|
| `app/models/integration.py` | Agregar `NOTION = "notion"` al enum `Platform` |
| `app/services/ingestion/cleaner.py` | Agregar `clean_notion()` y entry en `_CLEANERS` |
| `app/api/routers/ingestion.py` | Registrar `NotionConnector` en `_CONNECTORS` |
| `app/services/connectors/__init__.py` | Agregar `"notion"` a `__all__` |
| `app/services/briefing/generator.py` | Hook para publicar briefing en Notion |
| `app/services/commitments/detector.py` | Hook para crear row en Notion |
| `cli/config.py` | Agregar `NotionConfig` |
| `cli/prompts.py` | Textos de Notion en onboarding, platform menu |
| `cli/onboarding.py` | Step 2b opcional para Notion |
| `cli/commands.py` | Comandos `/notion` y `/prep` |
| `cli/background.py` | Notion sync en el loop de background |
| `requirements.txt` | Agregar `notion-client>=2.0` |

---

## Dependencias Nuevas

| Paquete | Versión | Uso |
|---|---|---|
| `notion-client` | `>=2.0,<3.0` | SDK oficial de Notion API (async) |

---

## Modelo de Autonomía Progresiva

Esta feature establece las bases para autonomía futura:

**Fase actual (colaborativa):**
- El asistente publica, el usuario revisa y edita
- Cambios del usuario en Notion se reflejan en secondBrain
- El asistente no toma acciones sin que el usuario pueda verlas

**Futuro (autónoma, fuera de scope actual):**
- El asistente puede mover commitments entre estados
- El asistente puede crear tareas derivadas de compromisos
- El asistente puede responder mensajes (ghost-write) y registrar la acción en Notion
- El asistente puede crear páginas de análisis proactivamente
- Cada acción autónoma queda loggeada en Notion como audit trail

El Notion del asistente funciona como **surface de transparencia**: todo lo que el asistente hace o planea hacer es visible ahí. Esto construye confianza antes de delegar más autonomía.

---

## Fases de Implementación

### Fase 9A: NotionConnector (Lectura)
- `notion.py` conector con fetch de páginas y databases
- `blocks.py` para conversión de bloques a texto
- `clean_notion()` en cleaner
- Registro en `_CONNECTORS`, Platform enum, `__init__`
- Tests unitarios + integración

### Fase 9B: NotionPublisher + Workspace Setup
- `publisher.py` con setup de workspace (página raíz + databases)
- Publicación de briefings y commitments
- `cli/notion_setup.py` para onboarding
- Modificar `cli/onboarding.py` para Step 2b
- Tests unitarios + integración

### Fase 9C: Sync Bidireccional + Background
- `sync.py` para sync bidireccional de commitments
- Integrar en `BackgroundSync`
- Hooks en `BriefingGenerator` y `CommitmentDetector`
- Meeting prep (generación + publicación)
- Comandos `/notion` y `/prep`
- Tests de sync + edge cases

### Fase 9D: Weekly Digest + Polish
- Generación de weekly digest
- Publicación como página en Notion
- Scheduler para generación semanal (viernes)
- Manejo de errores, reconexión, rate limiting robusto
- Tests e2e del flujo completo

---

## Criterios de Aceptación

### Lectura
- [ ] Notion aparece como plataforma opcional en el onboarding
- [ ] Las páginas de Notion se ingesan al knowledge base
- [ ] Las databases de Notion se ingesan (propiedades + contenido)
- [ ] `/sync notion` sincroniza solo páginas modificadas desde la última sync
- [ ] Queries RAG encuentran contenido de Notion junto con otras fuentes

### Escritura
- [ ] Al activar Notion se crea la página raíz con 3 databases
- [ ] Los commitments nuevos aparecen en la database de Notion
- [ ] El daily briefing se publica como página en Notion
- [ ] El meeting prep se genera y publica antes de cada meeting

### Sync Bidireccional
- [ ] Cambiar status de un commitment en Notion se refleja en secondBrain
- [ ] Cambiar status en secondBrain se refleja en Notion
- [ ] Conflictos se resuelven con last-write-wins
- [ ] No se duplican entries al re-syncear

### Onboarding
- [ ] Notion es **opcional** — skip no afecta ninguna otra feature
- [ ] Se puede activar después con `/notion connect`
- [ ] Se puede desactivar con `/notion disconnect`
- [ ] Las instrucciones de setup son claras (crear integration, compartir páginas)

### Autonomía
- [ ] Toda acción del asistente es visible en Notion
- [ ] El usuario puede editar/revertir cualquier cosa que el asistente publicó
- [ ] No hay acciones ocultas — Notion es el audit trail
