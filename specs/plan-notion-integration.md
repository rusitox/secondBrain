# Plan de Implementación: Integración Notion

> Spec de referencia: `specs/notion-integration.md`
> Estado: Pendiente de aprobación

---

## Resumen

Integración de Notion como fuente de lectura y superficie de escritura para el asistente digital. Se implementa en 4 fases incrementales (9A–9D), cada una con CR + QA antes de avanzar.

**Decisión técnica clave**: usar `httpx` directamente en vez del SDK `notion-client`. Todos los conectores existentes (Outlook, Teams, Slack, Fathom) usan `httpx` directamente. Mantener consistencia evita una dependencia extra y permite reutilizar el patrón de retry/backoff ya probado en `TeamsConnector._api_call()`.

---

## Fase 9A: NotionConnector (Lectura)

### Objetivo
Leer páginas y databases del Notion del usuario e ingresarlas al pipeline de ingestion existente.

### Archivos a crear

| Archivo | Qué hace |
|---|---|
| `app/services/connectors/notion.py` | `NotionConnector(BaseConnector)` — fetch de páginas/databases via Notion API |
| `app/services/notion/__init__.py` | Package init (solo exports) |
| `app/services/notion/blocks.py` | Conversión de bloques Notion → texto plano |
| `tests/unit/test_notion_connector.py` | Tests unitarios del conector |
| `tests/unit/test_notion_blocks.py` | Tests de conversión de bloques |
| `tests/integration/test_notion_connector.py` | Tests con HTTP mocked (respx) |

### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `app/models/integration.py:17` | Agregar `NOTION = "notion"` al enum `Platform` |
| `app/services/connectors/__init__.py` | Agregar `"notion"` a `__all__` |
| `app/api/routers/ingestion.py:35-40` | Registrar `NotionConnector` en `_CONNECTORS` |
| `app/services/ingestion/cleaner.py` | Agregar `clean_notion()` + entry en `_CLEANERS` |

### Detalle de implementación

#### `notion.py` — NotionConnector

```python
class NotionConnector(BaseConnector):
    platform = "notion"
    NOTION_API_BASE = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"
    RATE_LIMIT = 3  # req/s

    async def fetch_items(self, access_token, since=None) -> List[ConnectorItem]:
        # 1. POST /search con filtro last_edited_time > since
        # 2. Iterar resultados (paginados)
        # 3. Para cada page: GET /blocks/{id}/children → blocks_to_text()
        # 4. Para cada database_item: extraer propiedades + contenido
        # 5. Retornar ConnectorItems

    async def validate_token(self, access_token) -> bool:
        # GET /users/me — 200 = válido

    async def _api_call(self, client, headers, method, url, **kwargs):
        # Retry con backoff en 429 (mismo patrón que TeamsConnector)
        # Semáforo asyncio.Semaphore(3) para 3 req/s
```

**Headers requeridos**: `Authorization: Bearer {token}`, `Notion-Version: 2022-06-28`

**Paginación**: `start_cursor` / `has_more` en la response. Max 100 items por request.

**Filtrado por fecha**: El endpoint `/search` no soporta filtro por fecha directamente. Estrategia: buscar todo y filtrar client-side por `last_edited_time > since`. Para workspaces grandes, usar el `sort` del search por `last_edited_time` descendente y cortar cuando se pasa del `since`.

#### `blocks.py` — Conversión de bloques

```python
def blocks_to_text(blocks: List[Dict]) -> str:
    """Convierte bloques de Notion a texto plano."""
    # paragraph, heading_1/2/3 → texto directo con ## para headings
    # bulleted_list_item → "• " + texto
    # numbered_list_item → "1. " + texto
    # to_do → "[x]" / "[ ]" + texto
    # code → fenced code block (```lang\n...\n```)
    # quote → "> " + texto
    # table → markdown table
    # child_page, child_database → ignorar (se fetchean aparte)
    # image, file, video, embed → ignorar (MVP text-only)
    # toggle → texto (sin interactividad)
    # callout → "> 💡 " + texto
    # divider → "---"

def extract_rich_text(rich_text_array: List[Dict]) -> str:
    """Extrae texto plano de un array de rich_text de Notion."""
    # Concatenar plain_text de cada element
```

**Recursividad**: Los bloques pueden tener `has_children=True`. Para estos, hacer GET recursivo de sus hijos (con profundidad máxima de 3 niveles para evitar loops).

#### `cleaner.py` — clean_notion()

Patrones a limpiar:
- IDs internos de Notion que puedan filtrarse (UUIDs de 32 chars)
- Whitespace excesivo de la conversión de bloques
- Markers de bloques vacíos

```python
_NOTION_PATTERNS = [
    re.compile(r"[a-f0-9]{32}"),  # Notion block IDs que se filtren
    re.compile(r"\n{3,}"),        # Triple+ newlines → double
]

def clean_notion(text: str) -> str:
    result = _apply_patterns(text, _NOTION_PATTERNS)
    return _normalize_whitespace(result)
```

Agregar a `_CLEANERS`: `"notion": clean_notion`

#### Platform enum

En `app/models/integration.py:17-21`:
```python
class Platform(str, enum.Enum):
    SLACK = "slack"
    OUTLOOK = "outlook"
    TEAMS = "teams"
    FATHOM = "fathom"
    NOTION = "notion"  # ← agregar
```

**Nota**: Esto requiere una migración Alembic para actualizar el enum en PostgreSQL. Crear migración: `ALTER TYPE platform_enum ADD VALUE 'notion'`.

### Verificación

- [ ] `NotionConnector` implementa `BaseConnector` correctamente
- [ ] `blocks_to_text()` convierte los 10+ tipos de bloques soportados
- [ ] Rate limiting con semáforo (3 req/s) + retry en 429
- [ ] Paginación correcta con `start_cursor`
- [ ] Filtro por `since` funciona
- [ ] `clean_notion()` registrada en `_CLEANERS`
- [ ] Platform enum incluye NOTION
- [ ] Migración Alembic creada
- [ ] Tests pasan

---

## Fase 9B: NotionPublisher + Workspace Setup

### Objetivo
Crear el workspace del asistente en Notion del usuario y publicar briefings y commitments.

### Archivos a crear

| Archivo | Qué hace |
|---|---|
| `app/services/notion/publisher.py` | `NotionPublisher` — crea workspace, publica contenido |
| `app/services/notion/config.py` | `NotionWorkspaceConfig` dataclass |
| `cli/notion_setup.py` | Flujo interactivo de setup de Notion (CLI) |
| `tests/unit/test_notion_publisher.py` | Tests del publisher |
| `tests/integration/test_notion_publisher.py` | Tests con HTTP mocked |

### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `cli/config.py` | Agregar campo `notion: Optional[Dict]` + `NotionConfig` dataclass |
| `cli/onboarding.py:217` | Agregar Step 2b opcional post-platforms |
| `cli/prompts.py` | Textos de Notion (instrucciones de setup, menú) |

### Detalle de implementación

#### `publisher.py` — NotionPublisher

```python
class NotionPublisher:
    NOTION_API_BASE = "https://api.notion.com/v1"

    def __init__(self, token: str, workspace_config: NotionWorkspaceConfig):
        self._token = token
        self._config = workspace_config

    async def setup_workspace(self) -> NotionWorkspaceConfig:
        """Crea página raíz + 3 databases. Se ejecuta una sola vez."""
        # 1. POST /pages — crear "🤖 secondBrain" como child de workspace
        # 2. POST /databases — crear Commitments DB (7 propiedades)
        # 3. POST /databases — crear Briefings DB (3 propiedades)
        # 4. POST /databases — crear Meeting Prep DB (4 propiedades)
        # 5. Guardar IDs en config y retornar

    async def publish_briefing(self, briefing: BriefingResult) -> str:
        """Crear una entry en la Briefings database con el contenido del briefing."""
        # 1. Convertir briefing_text a bloques de Notion (text_to_blocks)
        # 2. POST /pages — crear page en la database con propiedades + children blocks
        # 3. Retornar URL

    async def create_commitment_row(self, commitment: Dict) -> str:
        """Crear una row en la Commitments database."""
        # POST /pages con propiedades: Title, Status, Priority, Due Date, Owner, Source, Detected

    async def update_commitment_row(self, notion_page_id: str, updates: Dict) -> None:
        """Actualizar propiedades de un commitment en Notion."""
        # PATCH /pages/{id}
```

#### `blocks.py` — Agregar conversión inversa

Extender el archivo creado en 9A con:
```python
def text_to_blocks(text: str) -> List[Dict]:
    """Convierte texto/markdown a bloques de Notion API."""
    # Parsear líneas:
    # ## heading → heading_2 block
    # • bullet → bulleted_list_item
    # 1. numbered → numbered_list_item
    # > quote → quote block
    # ```code``` → code block
    # plain text → paragraph block
    # --- → divider block
```

#### `config.py` — NotionWorkspaceConfig

```python
@dataclass
class NotionWorkspaceConfig:
    enabled: bool = False
    root_page_id: Optional[str] = None
    commitments_db_id: Optional[str] = None
    briefings_db_id: Optional[str] = None
    meeting_prep_db_id: Optional[str] = None
    read_mode: str = "all"
    selected_page_ids: List[str] = field(default_factory=list)
    excluded_page_ids: List[str] = field(default_factory=list)
    last_read_sync: Optional[str] = None
    last_write_sync: Optional[str] = None
```

#### `cli/config.py` — Cambios

Agregar a `CLIConfig`:
```python
notion: Optional[Dict[str, Any]] = None  # NotionWorkspaceConfig serializada
```

Actualizar `load()`, `save()`, `reset()` para incluir el campo `notion`.

#### `cli/onboarding.py` — Step 2b

Insertar entre Step 2 (platforms) y Step 3 (identity). El step es totalmente opcional:
1. Preguntar si quiere conectar Notion (y/n)
2. Si sí: pedir token, validar, preguntar read_mode, ejecutar setup_workspace
3. Si no: skip sin efecto en el resto del onboarding

La inserción se hace después de `_step_platforms()` (línea ~250), llamando a un método en `cli/notion_setup.py` para mantener `onboarding.py` limpio.

#### `cli/notion_setup.py` — Flujo de setup

```python
class NotionSetup:
    async def run_setup(self, config: CLIConfig) -> bool:
        """Flujo interactivo: token → validar → read_mode → workspace setup."""

    async def connect(self, config: CLIConfig) -> bool:
        """Usado por /notion connect (mismo flujo que onboarding)."""

    def disconnect(self, config: CLIConfig) -> None:
        """Desconectar: borrar config de Notion."""
```

### Verificación

- [ ] `setup_workspace()` crea página raíz + 3 databases correctamente
- [ ] `publish_briefing()` genera página legible en Notion
- [ ] `create_commitment_row()` crea row con todas las propiedades
- [ ] `text_to_blocks()` convierte markdown a bloques válidos
- [ ] Onboarding Step 2b es skip-able sin afectar el flujo
- [ ] Config persiste IDs del workspace
- [ ] Token se valida antes de proceder
- [ ] Tests pasan

---

## Fase 9C: Sync Bidireccional + Background + Commands

### Objetivo
Sincronización bidireccional de commitments, integración con background sync, hooks en briefing/commitment, y slash commands.

### Archivos a crear

| Archivo | Qué hace |
|---|---|
| `app/services/notion/sync.py` | `NotionSync` — sync bidireccional de commitments |
| `tests/unit/test_notion_sync.py` | Tests del sync |

### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `cli/background.py:68-80` | Agregar Notion sync después de platform sync |
| `cli/commands.py:34-48` | Agregar `/notion` y `/prep` al COMMANDS dict + handlers |
| `app/services/briefing/generator.py:111` | Hook post-generación para publicar en Notion |
| `app/services/commitments/detector.py` | Hook post-detección para crear row en Notion |

### Detalle de implementación

#### `sync.py` — NotionSync

```python
class NotionSync:
    def __init__(self, publisher: NotionPublisher):
        self._publisher = publisher

    async def sync_commitments(self, db: AsyncSession, user_id: uuid.UUID) -> SyncResult:
        """Sync bidireccional de commitments."""
        # 1. Leer commitments locales (con notion_page_id si existe)
        # 2. Query Notion Commitments database
        # 3. Match por notion_page_id
        # 4. Nuevos locales sin notion_page_id → crear en Notion
        # 5. Cambios en Notion (status) → actualizar local
        # 6. Cambios locales → actualizar Notion
        # 7. Conflict resolution: last-write-wins (updated_at vs last_edited_time)
```

**Nota sobre el modelo Commitment**: necesita un campo `notion_page_id: Optional[str]` para trackear el mapping. Esto requiere una migración Alembic (simple ALTER TABLE ADD COLUMN).

Archivo afectado: `app/models/commitment.py` — agregar:
```python
notion_page_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
```

#### `background.py` — Extender _sync_all

Después del loop de platforms (línea ~80), agregar:
```python
# Notion sync (if enabled)
if self._config.notion and self._config.notion.get("enabled"):
    try:
        # 1. Sync lectura (ingest páginas modificadas)
        await self._api.sync_platform("notion")
        # 2. Sync escritura (commitments bidireccional)
        # El publisher/sync se instancia con el token del integration
        # y se ejecuta sync_commitments
    except APIError as e:
        logger.warning("Notion sync failed: %s", e.detail)
```

#### `commands.py` — Slash commands

Agregar al `COMMANDS` dict:
```python
"/notion": "Notion integration (connect|disconnect|status|sync|workspace)",
"/prep": "Generate meeting prep (/prep Meeting Name)",
```

Handler `_cmd_notion(args)`:
- `connect` → `NotionSetup.connect()`
- `disconnect` → `NotionSetup.disconnect()`
- `status` → mostrar estado (enabled, last sync, workspace URL)
- `sync` → sync manual (lectura + escritura)
- `workspace` → abrir URL en browser (`webbrowser.open()`)

Handler `_cmd_prep(args)`:
- Generar meeting prep para el meeting indicado
- Publicar en Notion si está habilitado
- Mostrar resultado en CLI

#### `briefing/generator.py` — Hook post-generación

Después de `return result` (línea ~112), agregar hook:
```python
# Notion publish hook — called by the orchestrator, not here
# El hook se invoca desde el CLI/background, no desde el generator mismo,
# para evitar acoplar el generator al publisher.
```

**Decisión**: NO modificar `generator.py` directamente. En cambio, el hook se ejecuta en `background.py` y en `commands.py._cmd_briefing()` después de llamar al generator. Esto mantiene el generator desacoplado.

#### `commitments/detector.py` — Hook post-detección

Mismo enfoque: el hook se ejecuta desde el caller (pipeline/background), no desde el detector. El pipeline de ingestion ya retorna los commitments detectados; el caller puede pasarlos al publisher.

### Verificación

- [ ] Sync bidireccional crea/actualiza commitments en ambas direcciones
- [ ] Conflictos se resuelven con last-write-wins
- [ ] No se duplican entries al re-syncear
- [ ] Background sync incluye Notion cuando está habilitado
- [ ] `/notion status` muestra info correcta
- [ ] `/notion sync` ejecuta sync manual
- [ ] `/notion connect/disconnect` funcionan
- [ ] `/prep` genera y publica meeting prep
- [ ] Migración Alembic para `notion_page_id`
- [ ] Tests pasan

---

## Fase 9D: Weekly Digest + Polish

### Objetivo
Generación de weekly digest, scheduling, manejo robusto de errores, y polish general.

### Archivos a crear

| Archivo | Qué hace |
|---|---|
| `app/services/notion/digest.py` | `WeeklyDigestGenerator` — genera resumen semanal |
| `tests/unit/test_notion_digest.py` | Tests del digest |

### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `app/services/notion/publisher.py` | Agregar `publish_weekly_digest()` |
| `cli/background.py` | Agregar scheduler semanal (viernes) para digest |
| `app/services/notion/publisher.py` | Retry robusto, reconexión, error handling |
| `app/services/connectors/notion.py` | Edge cases: páginas sin permisos, bloques corruptos |

### Detalle de implementación

#### `digest.py` — WeeklyDigestGenerator

```python
class WeeklyDigestGenerator:
    async def generate(self, db, user_id, week_start, week_end) -> DigestResult:
        # 1. Commitments de la semana: cumplidos, nuevos, vencidos
        # 2. Métricas: documentos procesados, queries, syncs
        # 3. Highlights: insights más relevantes (top RAG queries)
        # 4. Plan próxima semana: calendar + commitments pendientes
        # 5. Generar texto con Claude
```

#### Background scheduler

En `background.py`, agregar check en `_sync_all()`:
```python
# Weekly digest (viernes después de las 17:00 hora local del usuario)
if self._should_generate_digest():
    digest = await self._generate_and_publish_digest()
```

#### Polish y error handling

- Retry en todas las llamadas a Notion API (ya implementado en 9A)
- Manejar token expirado/revocado: detectar 401, marcar `enabled=False`, notificar al usuario
- Manejar páginas sin permiso: 403 → skip + log warning
- Manejar rate limit sostenido: backoff exponencial hasta 60s
- Manejar workspace eliminado: si `root_page_id` retorna 404, ofrecer re-setup

### Verificación

- [ ] Digest semanal se genera correctamente
- [ ] Se publica como página en Notion
- [ ] Scheduler se dispara los viernes
- [ ] Token revocado se maneja gracefully
- [ ] Páginas sin permiso se skipean sin crash
- [ ] Rate limit sostenido no bloquea el sistema
- [ ] Flujo completo end-to-end funciona

---

## Dependencias entre fases

```
9A (Connector lectura) → 9B (Publisher + setup)
                            ↓
                         9C (Sync + background + commands)
                            ↓
                         9D (Digest + polish)
```

Cada fase es self-contained y deployable. 9A puede funcionar solo como conector de lectura. 9B agrega escritura. 9C conecta todo. 9D es polish.

---

## Migración de base de datos

### Migración 1 (Fase 9A)
```sql
ALTER TYPE platform_enum ADD VALUE 'notion';
```

### Migración 2 (Fase 9C)
```sql
ALTER TABLE commitments ADD COLUMN notion_page_id VARCHAR(36);
CREATE INDEX ix_commitments_notion_page_id ON commitments (notion_page_id);
```

---

## Dependencias de paquetes

**Ninguna nueva**. Se usa `httpx` (ya en requirements.txt) en vez de `notion-client` para consistencia con los demás conectores.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Rate limit de 3 req/s con workspaces grandes | Semáforo + paginación + filtro por `since` |
| Notion API cambia la estructura de bloques | `blocks_to_text()` ignora tipos desconocidos |
| Token revocado entre syncs | Detectar 401, desactivar, notificar |
| Conflictos en sync bidireccional | Last-write-wins con timestamps |
| Notion `/search` no filtra por fecha server-side | Sort descendente + cortar client-side |

---

## Estimación por fase

| Fase | Archivos nuevos | Archivos modificados | Tests |
|---|---|---|---|
| 9A | 4 | 4 | ~20 |
| 9B | 4 | 3 | ~15 |
| 9C | 1 | 5 | ~15 |
| 9D | 1 | 3 | ~10 |
| **Total** | **10** | **15** | **~60** |
