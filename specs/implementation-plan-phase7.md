# Plan de Implementación: Fase 7 — Onboarding Chat Interface

## Contexto

Las Fases 1-6 del MVP están completas: backend FastAPI con ingesta, RAG, detección de compromisos, briefing diario, y agente multi-tool. Todo funciona vía API REST pero **no existe interfaz de usuario**. La Fase 7 crea un CLI conversacional que sirve como punto de entrada único: onboarding guiado + chat diario.

## Grafo de Dependencias

```
Phases 1-6 (Backend completo)
       │
Phase 7A (CLI Foundation + API Identity)
       │
Phase 7B (Onboarding Wizard)
       │
Phase 7C (Chat Diario + Comandos)
       │
Phase 7D (Background Sync + Alertas Proactivas)
```

> Cada sub-fase produce un entregable ejecutable. 7A es la base, 7B-D son incrementales.

---

## Phase 7A: CLI Foundation + Identity API

**Objetivo**: Infraestructura del CLI (config, display, API client) + endpoints de Identity que el onboarding necesita. Al final de esta fase: el CLI arranca, se conecta al backend, y puede crear un usuario.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| CLI Core | `cli/__init__.py`, `cli/__main__.py` (entry point: `python -m cli`), `cli/main.py` (argparse + async event loop + inicialización) |
| Config | `cli/config.py` (`CLIConfig` dataclass — carga/guarda `~/.secondbrain/config.json`, server_url, user_id, onboarding state) |
| Display | `cli/display.py` (wrapper de `rich`: `Console`, `print_panel()`, `print_table()`, `print_error()`, `print_success()`, `spinner()`, `progress_bar()`) |
| API Client | `cli/api_client.py` (`APIClient` class — httpx async, métodos tipados para cada endpoint, manejo de errores HTTP, header `X-User-Id` automático) |
| Identity API | `app/api/routers/identity.py` (POST + GET + PATCH `/users/{user_id}/identity`), `app/api/schemas/identity.py` (`IdentityCreate`, `IdentityRead`, `IdentityUpdate`) |
| Stats API | `app/api/routers/users.py` — agregar `GET /users/{user_id}/stats` (conteo de docs, commitments, integrations) |
| Tests | `tests/unit/test_cli_config.py`, `tests/unit/test_cli_display.py`, `tests/unit/test_cli_api_client.py`, `tests/unit/test_identity_api.py`, `tests/integration/test_identity_crud.py` |

**Modificar:**
- `requirements.txt` — agregar `rich>=13.0`, `prompt_toolkit>=3.0`
- `app/main.py` — registrar `identity.router`
- `app/api/routers/__init__.py` — agregar `"identity"`
- `app/services/__init__.py` — agregar `"identity"`
- `tests/conftest.py` — verificar que tabla `identities` ya está en DDL (debería estar desde Fase 1)

**Decisiones clave:**
- El CLI es un paquete separado (`cli/`) que consume la API REST, no importa directamente de `app/`. Esto mantiene la separación frontend/backend y permite reemplazar el CLI por una web app sin cambiar nada del backend
- `CLIConfig` se persiste en `~/.secondbrain/config.json` — no en el directorio del proyecto
- `APIClient` es async (httpx) con timeout de 30s para operaciones normales, 300s para syncs
- `display.py` encapsula toda la lógica de `rich` — si se quiere cambiar la librería de display, solo se toca este archivo
- Identity CRUD usa el mismo patrón de servicio que users/commitments/integrations

**Esquema de Identity API:**

```python
# POST /users/{user_id}/identity
class IdentityCreate(BaseModel):
    persona_description: str = ""
    tone_guidelines: str = ""
    heuristics: Dict[str, Any] = {}

# GET /users/{user_id}/identity → IdentityRead
class IdentityRead(BaseModel):
    id: UUID
    user_id: UUID
    persona_description: str
    tone_guidelines: str
    heuristics: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

# PATCH /users/{user_id}/identity
class IdentityUpdate(BaseModel):
    persona_description: Optional[str] = None
    tone_guidelines: Optional[str] = None
    heuristics: Optional[Dict[str, Any]] = None
```

**Esquema de Stats:**

```python
# GET /users/{user_id}/stats
class UserStats(BaseModel):
    documents_total: int
    commitments_pending: int
    commitments_overdue: int
    integrations_active: int
    integrations_total: int
    last_sync: Optional[datetime]
```

**APIClient — métodos principales:**

```python
class APIClient:
    async def create_user(name, email, timezone) -> dict
    async def get_user(user_id) -> dict
    async def create_identity(user_id, persona, tone, heuristics) -> dict
    async def get_identity(user_id) -> Optional[dict]
    async def update_identity(user_id, **fields) -> dict
    async def create_integration(user_id, platform, token, refresh) -> dict
    async def list_integrations(user_id) -> list
    async def sync_platform(platform) -> dict
    async def get_sync_status(integration_id) -> dict
    async def query(question) -> dict
    async def agent_query(question) -> dict
    async def get_briefing(user_id) -> dict
    async def get_commitments(filter) -> list
    async def get_stats(user_id) -> dict
    async def validate_connection() -> bool  # health check
```

**Verificación:**
- `python -m cli --help` funciona
- `python -m cli` muestra panel de bienvenida y detecta que no hay config
- Identity CRUD funciona via `/docs`
- Stats endpoint retorna conteos correctos
- Tests: `pytest tests/unit/test_cli_*.py tests/unit/test_identity_api.py`

---

## Phase 7B: Onboarding Wizard

**Objetivo**: Flujo de onboarding completo de 5 pasos, resumable. Al final de esta fase: un usuario nuevo puede configurar todo el sistema desde el CLI.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Onboarding | `cli/onboarding.py` (`OnboardingFlow` class — wizard de 5 pasos, estado persistido, skip/back) |
| Prompts | `cli/prompts.py` (textos de bienvenida, instrucciones por plataforma, mensajes de error, help text) |
| Validation | `cli/validators.py` (validadores de input: email, timezone, token format) |
| Tests | `tests/unit/test_onboarding_flow.py`, `tests/integration/test_onboarding_wizard.py` |

**Modificar:**
- `cli/main.py` — detectar si onboarding completo, si no → lanzar `OnboardingFlow`

**Los 5 pasos del OnboardingFlow:**

### Paso 1: `_step_welcome()` — Creación de cuenta
- Input: nombre, email, timezone (con validación + sugerencias)
- Acción: `api.create_user()` → guardar `user_id` en config
- Si el usuario ya existe (email duplicado): ofrecer login con ese user_id
- Persistir: `config.onboarding_step = 1`, `config.user_created = True`

### Paso 2: `_step_platforms()` — Conexión de plataformas
- Mostrar menú de plataformas (multiselect con números)
- Para cada plataforma seleccionada:
  1. Mostrar instrucciones específicas de dónde obtener el token
  2. Pedir token (input con `password=True` para ocultar)
  3. `api.create_integration()` → si falla validación, ofrecer retry/skip/help
  4. Si exitoso: mostrar info del workspace/cuenta conectada
- Persistir: `config.platforms_connected = ["slack", "outlook", ...]`
- Permite saltar (`skip`) y volver después

**Instrucciones por plataforma (en `prompts.py`):**

| Plataforma | URL para token | Tipo de token | Permisos necesarios |
|---|---|---|---|
| Outlook | `https://developer.microsoft.com/graph/graph-explorer` | OAuth2 access token | `Mail.Read`, `Calendars.Read` |
| Slack | `https://api.slack.com/apps` → OAuth & Permissions | Bot token (`xoxb-`) | `channels:history`, `channels:read`, `im:history`, `users:read` |
| Teams | Mismo que Outlook (MS Graph) | OAuth2 access token | `Chat.Read` |
| Fathom | `https://app.fathom.video/settings` → API | API key | Read access |

### Paso 3: `_step_identity()` — Configuración de estilo
- Input conversacional: rol, tono (preset o custom), reglas (loop hasta línea vacía)
- Mostrar resumen para confirmación
- Acción: `api.create_identity()` o `api.update_identity()`
- Persistir: `config.identity_configured = True`

### Paso 4: `_step_initial_import()` — Import de datos
- Selección de ventana temporal: 7/30/90 días / todo
- Para cada plataforma conectada:
  - `api.sync_platform(platform)` con progress bar
  - Mostrar resultado (docs creados, chunks, commitments)
- Al final: ofrecer review de commitments detectados
  - Tabla paginada con accept/edit/dismiss por item
- Persistir: `config.initial_import_done = True`

### Paso 5: `_step_preferences()` — Preferencias recurrentes
- Hora del briefing (validar 0-23:0-59, default 07:00)
- Tipo de alertas de commitments (inmediato / solo briefing / manual)
- Weekly digest (sí/no)
- Acción: `api.schedule_briefing()`, guardar en config
- Persistir: `config.preferences_set = True`, `config.onboarding_completed = True`

**Manejo de resume:**

```python
class OnboardingState:
    current_step: int = 0          # 0-5
    user_created: bool = False
    user_id: Optional[str] = None
    platforms_connected: List[str] = []
    identity_configured: bool = False
    initial_import_done: bool = False
    preferences_set: bool = False
```

Si el CLI detecta `onboarding_completed = False` y `current_step > 0`:
```
Welcome back, Mariano! You left off at step 3 (Identity Setup).

[c] Continue from step 3
[r] Restart onboarding
[s] Skip to chat (finish later with /setup)
```

**Verificación:**
- Flujo completo de onboarding de principio a fin (manual)
- Resume funciona: cerrar en paso 3, reabrir, continuar desde paso 3
- Plataforma con token inválido → error claro → retry/skip
- Tests mockean `APIClient` para validar flujo sin backend real

---

## Phase 7C: Chat Diario + Comandos

**Objetivo**: Loop principal del chat con queries en lenguaje natural y comandos `/`. Al final de esta fase: el usuario puede usar secondBrain como su asistente diario desde la terminal.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Chat | `cli/chat.py` (`ChatSession` class — loop principal de input/output, historial en memoria, routing) |
| Commands | `cli/commands.py` (`CommandRouter` class — dispatch de `/commands`, registro de handlers) |
| Tests | `tests/unit/test_chat_session.py`, `tests/unit/test_command_router.py`, `tests/integration/test_chat_commands.py` |

**Modificar:**
- `cli/main.py` — después de onboarding, lanzar `ChatSession`

**ChatSession — loop principal:**

```python
class ChatSession:
    async def run(self) -> None:
        """Main chat loop."""
        self._show_welcome_banner()
        while True:
            user_input = await self._get_input()  # prompt_toolkit
            if not user_input:
                continue
            if user_input.startswith("/"):
                await self._router.dispatch(user_input)
            else:
                await self._handle_query(user_input)
```

**Routing de queries:**
- Input normal → `api.agent_query(question)` (usa el agente multi-tool)
- Mostrar respuesta formateada con markdown (via `rich.Markdown`)
- Mostrar tools_used y sources como metadata discreta debajo de la respuesta

**Formato de respuesta:**

```
you> What's the status of the partnership deal?

  Searching memory, checking tasks...

┌─ Answer ─────────────────────────────────────────────┐
│ The partnership deal with PartnerCo is in final       │
│ review. Key points:                                   │
│                                                       │
│ • Laura sent the proposal v3 on Apr 15               │
│ • Bob (PartnerCo) requested minor changes to         │
│   pricing in a Slack message yesterday               │
│ • You committed to sending revised terms by Friday   │
│                                                       │
│ Action needed: Revise pricing terms (due Apr 18)     │
└──────────────────────────────────────────────────────┘
  tools: memory, tasks | sources: 3 documents
```

**CommandRouter — handlers registrados:**

| Comando | Handler | Acción |
|---|---|---|
| `/briefing` | `cmd_briefing()` | `api.get_briefing()` → mostrar briefing formateado |
| `/commitments` | `cmd_commitments()` | `api.get_commitments("pending")` → tabla de commitments |
| `/overdue` | `cmd_overdue()` | `api.get_commitments("overdue")` → tabla filtrada |
| `/sync` | `cmd_sync(platform?)` | Sync todas o una plataforma, con progress bar |
| `/connect` | `cmd_connect()` | Flujo de conexión de nueva plataforma (reusa `OnboardingFlow._step_platforms()`) |
| `/disconnect <p>` | `cmd_disconnect(platform)` | Confirmar + desactivar integración |
| `/status` | `cmd_status()` | Tabla de conexiones con last_sync |
| `/identity` | `cmd_identity()` | Ver/editar perfil (reusa `OnboardingFlow._step_identity()`) |
| `/settings` | `cmd_settings()` | Ver/editar preferencias de briefing/alertas |
| `/setup` | `cmd_setup()` | Re-lanzar onboarding completo |
| `/help` | `cmd_help()` | Mostrar tabla de comandos disponibles |
| `/quit` | `cmd_quit()` | Confirmación + salir limpio |

**Autocompletado:**
- `prompt_toolkit` con `WordCompleter` para comandos `/`
- Historial de inputs navegable con flechas arriba/abajo
- `prompt_toolkit.history.FileHistory("~/.secondbrain/history")`

**Banner de bienvenida (post-onboarding):**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  secondBrain — Your AI Chief of Staff
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Connected: Outlook, Slack, Fathom
  Documents: 1,586 | Commitments: 14 pending
  Last sync: 2 hours ago

  Type a question or /help for commands.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Verificación:**
- Chat loop funciona: input → agent query → respuesta formateada
- Todos los comandos `/` funcionan
- Autocompletado de `/` commands con Tab
- `/quit` sale limpio
- Tests: unit para routing, integration para flujo completo mockado

---

## Phase 7D: Background Sync + Alertas Proactivas

**Objetivo**: Sync periódico en background mientras el usuario chatea + alertas cuando se detectan nuevos commitments. Al final de esta fase: el sistema es proactivo.

**Archivos a crear:**

| Área | Archivos |
|---|---|
| Background | `cli/background.py` (`BackgroundSync` class — async task que corre sync periódico, emite eventos) |
| Alertas | `cli/alerts.py` (`AlertManager` class — recibe eventos de sync, formatea alertas, las inyecta en el chat) |
| Tests | `tests/unit/test_background_sync.py`, `tests/unit/test_alert_manager.py`, `tests/integration/test_background_flow.py` |

**Modificar:**
- `cli/chat.py` — integrar `BackgroundSync` y `AlertManager` en el loop principal
- `cli/config.py` — agregar `sync_interval_minutes` (default 30)

**BackgroundSync:**

```python
class BackgroundSync:
    """Runs periodic syncs in the background."""

    def __init__(self, api: APIClient, config: CLIConfig, 
                 on_new_commitments: Callable) -> None:
        self._api = api
        self._config = config
        self._callback = on_new_commitments
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        interval = self._config.preferences.get("sync_interval", 30) * 60
        while True:
            await asyncio.sleep(interval)
            for platform in self._config.connected_platforms:
                result = await self._api.sync_platform(platform)
                if result.get("commitments_detected", 0) > 0:
                    self._callback(platform, result)
```

**AlertManager — formato de alertas:**

Las alertas se muestran entre inputs del usuario, sin interrumpir lo que esté escribiendo:

```python
class AlertManager:
    def on_new_commitments(self, platform: str, result: dict) -> None:
        """Called by BackgroundSync when new commitments found."""
        # Queue alert for display
        self._pending_alerts.append(Alert(
            type="commitment",
            platform=platform,
            count=result["commitments_detected"],
            items=result.get("commitments", []),
        ))

    async def show_pending(self, console: Console) -> None:
        """Show pending alerts (called between user inputs)."""
        for alert in self._pending_alerts:
            console.print(Panel(
                self._format_alert(alert),
                title="New commitments detected",
                border_style="yellow",
            ))
        self._pending_alerts.clear()
```

**Integración con ChatSession:**

```python
# En chat.py, el loop principal:
async def run(self) -> None:
    await self._background.start()
    try:
        while True:
            # Show pending alerts before prompting
            await self._alerts.show_pending(self._console)
            user_input = await self._get_input()
            ...
    finally:
        await self._background.stop()
```

**Verificación:**
- El sync corre en background sin bloquear el input
- Nuevos commitments detectados se muestran como alerta
- `/sync` manual sigue funcionando
- El interval es configurable via `/settings`
- `ctrl+c` o `/quit` hacen cleanup del background task
- Tests: mock del timer para no esperar 30 min en tests

---

## Resumen por Sub-Fase

| Sub-Fase | Entregable | Archivos nuevos | Archivos modificados | Tests |
|---|---|---|---|---|
| 7A | CLI foundation + Identity API | 8 CLI + 2 API | 4 (requirements, main, routers init, services init) | 5 |
| 7B | Onboarding wizard (5 pasos) | 3 CLI | 1 (cli/main.py) | 2 |
| 7C | Chat diario + comandos | 2 CLI | 1 (cli/main.py) | 3 |
| 7D | Background sync + alertas | 2 CLI | 2 (cli/chat.py, cli/config.py) | 3 |
| **Total** | **CLI completo** | **15** | **8** | **13** |

---

## Archivos Críticos

- `cli/api_client.py` — toda la comunicación CLI↔Backend pasa por acá
- `cli/config.py` — estado persistido del usuario (onboarding, preferencias, conexiones)
- `cli/onboarding.py` — primera impresión del usuario, flujo más complejo
- `cli/chat.py` — loop principal de uso diario
- `app/api/routers/identity.py` — endpoint nuevo que el onboarding necesita

## Dependencias Nuevas

| Paquete | Versión | Uso |
|---|---|---|
| `rich` | `>=13.0` | Formato de terminal: panels, tablas, markdown, progress, spinners |
| `prompt_toolkit` | `>=3.0` | Input avanzado: historial, autocompletado, key bindings async |

## Workflow por Sub-Fase

Mismo patrón que Fases 1-6:
1. Implementar
2. Escribir tests
3. Correr test suite completa (`pytest tests/`)
4. Code review (fix CRITICALs + WARNINGs)
5. QA contra spec
6. Commit + push
