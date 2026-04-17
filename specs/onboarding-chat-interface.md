# Onboarding Chat Interface: AI Chief of Staff

## 🎯 Objetivo

Crear una interfaz conversacional (CLI/terminal) que sea el punto de entrada único del usuario al sistema. El chat guía al usuario a través del onboarding completo: creación de cuenta, conexión de plataformas, configuración de identidad/estilo, import inicial de datos, y configuración de interacciones recurrentes. Una vez completado el onboarding, el mismo chat se convierte en la interfaz principal de uso diario.

## 📦 Alcance

### En Scope (MVP)
- CLI interactivo con formato de chat (prompt + respuestas formateadas)
- Flujo de onboarding guiado paso a paso
- Conexión de integraciones (Slack, Outlook, Teams, Fathom)
- Configuración de identidad y estilo de comunicación
- Import inicial masivo de datos históricos
- Configuración de preferencias de interacción recurrente (briefing, alertas)
- Transición fluida de onboarding a uso diario (query, briefing, agent)

### Fuera de Scope (MVP)
- Interfaz web/mobile (fase futura)
- Interfaz de voz (fase futura)
- OAuth2 browser redirect flow (MVP usa token manual)
- Notificaciones push

---

## 🏗️ Arquitectura

### Componentes

```
┌──────────────────────────────────────────────────────────┐
│                    CLI Chat Interface                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ OnboardingFlow│  │ ChatSession  │  │ CommandRouter   │  │
│  │  (wizard)    │  │  (main loop) │  │  (dispatch)     │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬────────┘  │
│         │                │                    │           │
│         └────────────────┴────────────────────┘           │
│                          │                                │
│                    ┌─────┴──────┐                         │
│                    │ APIClient  │                         │
│                    │ (httpx)    │                         │
│                    └─────┬──────┘                         │
│                          │                                │
└──────────────────────────┼────────────────────────────────┘
                           │ HTTP
                    ┌──────┴──────┐
                    │  FastAPI    │
                    │  Backend    │
                    └─────────────┘
```

### Módulos

| Módulo | Responsabilidad |
|---|---|
| `cli/main.py` | Entry point, inicialización, event loop |
| `cli/chat.py` | `ChatSession` — loop principal de input/output, historial, formato |
| `cli/onboarding.py` | `OnboardingFlow` — wizard de onboarding completo |
| `cli/commands.py` | `CommandRouter` — dispatch de comandos del chat diario |
| `cli/api_client.py` | `APIClient` — wrapper httpx async contra el backend FastAPI |
| `cli/display.py` | Formateo de output: markdown, tablas, colores, spinners |
| `cli/config.py` | Configuración local del CLI (server URL, user_id, estado de onboarding) |

---

## ✨ Flujos de Usuario

### 1. Primera Ejecución — Onboarding Completo

El onboarding se ejecuta automáticamente cuando el usuario no tiene configuración local. Se divide en 5 pasos, cada uno conversacional y con la posibilidad de saltar o volver atrás.

#### Paso 1: Bienvenida y Creación de Cuenta

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Welcome to secondBrain — Your AI Chief of Staff
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

I'm your personal AI assistant. I'll help you connect your
communication platforms, learn your style, and start tracking
your commitments automatically.

Let's get you set up. This will take about 5 minutes.

What's your name?
> Mariano Ortega

And your email?
> mariano@company.com

What timezone are you in? (e.g., America/Argentina/Buenos_Aires)
> America/Argentina/Buenos_Aires

Great, Mariano! Your account is ready. Let's connect your platforms.
```

**Acciones backend:**
- `POST /users` → crear usuario
- Guardar `user_id` en config local (`~/.secondbrain/config.json`)

#### Paso 2: Conexión de Plataformas

El sistema presenta las plataformas disponibles y guía al usuario para conectar cada una. El MVP usa tokens manuales (no OAuth redirect).

```
━━━ Step 2/5: Connect Your Platforms ━━━

Which platforms do you use? (select all that apply)

  [1] Microsoft Outlook (emails + calendar)
  [2] Slack (messages + channels)
  [3] Microsoft Teams (chat)
  [4] Fathom (meeting transcripts)
  [s] Skip for now

> 1, 2, 4

Let's connect Microsoft Outlook first.

I need a Microsoft Graph API access token. You can get one from:
  https://developer.microsoft.com/graph/graph-explorer

Paste your access token:
> eyJ0eXAiOiJKV1Qi...

Validating token... ✓ Connected to Outlook!
  Found: mariano@company.com
  Access to: Mail, Calendar

Now let's connect Slack.

I need a Slack Bot Token (starts with xoxb-). You can create one at:
  https://api.slack.com/apps → OAuth & Permissions

Paste your bot token:
> xoxb-1234-5678-abc

Validating token... ✓ Connected to Slack!
  Workspace: My Company
  Channels accessible: 12

Now let's connect Fathom.

I need your Fathom API key. Find it at:
  https://app.fathom.video/settings → API

Paste your API key:
> fathom_key_abc123

Validating token... ✓ Connected to Fathom!
  Recordings available: 47

Platforms connected: Outlook ✓  Slack ✓  Fathom ✓
```

**Acciones backend por cada plataforma:**
1. `POST /integrations` → crear integración con token encriptado
2. Validar token via connector: `connector.validate_token(token)`
3. Si falla: mostrar error específico, ofrecer reintentar o saltar

**Manejo de errores:**
```
Validating token... ✗ Token rejected

The token might be expired or missing permissions.
Common fixes:
  - Ensure the token has Mail.Read and Calendars.Read scopes
  - Generate a fresh token if it's expired

[r] Retry with a new token
[s] Skip Outlook for now
[h] Help me get a token

> r
```

#### Paso 3: Configuración de Identidad y Estilo

```
━━━ Step 3/5: Tell Me About You ━━━

I'll adapt my communication style to match yours.

How would you describe your professional role? (brief, 1-2 sentences)
> I'm a CTO at a startup. I manage engineering, product, and talk to investors.

What tone should I use when communicating on your behalf?
  [1] Professional and formal
  [2] Friendly but professional
  [3] Casual and direct
  [4] Let me describe it myself

> 4

Describe the tone you'd like:
> Direct, no fluff, action-oriented. Use bullet points. Mix English and Spanish when natural.

Are there any specific rules or heuristics I should know about?
(e.g., "Always prioritize investor requests", "Bob = CTO of PartnerCo")
Type each one and press Enter. Empty line to finish.

> Investor meetings are always top priority
> When I say "urgent" it means same-day
> My co-founder is Laura — she handles sales
>

Got it! Here's your profile:

  Role: CTO at a startup (engineering, product, investor relations)
  Tone: Direct, no-fluff, action-oriented, bilingual EN/ES
  Rules:
    • Investor meetings = top priority
    • "Urgent" = same-day
    • Laura (co-founder) = sales

Does this look right? [y/n/edit]
> y
```

**Acciones backend:**
- `POST /identities` (nuevo endpoint necesario) → crear Identity con:
  - `persona_description`: rol + contexto
  - `tone_guidelines`: estilo de comunicación
  - `heuristics`: reglas como JSONB `{"investor_priority": true, "urgent_means_sameday": true, ...}`

#### Paso 4: Import Inicial de Datos

```
━━━ Step 4/5: Initial Data Import ━━━

Now I'll pull your recent data from connected platforms.
This first sync might take a few minutes depending on volume.

How far back should I go?
  [1] Last 7 days
  [2] Last 30 days (recommended)
  [3] Last 90 days
  [4] Everything available

> 2

Starting initial sync...

  Outlook (emails)...     ████████████████████ 342 emails    ✓
  Outlook (calendar)...   ████████████████████  28 events    ✓
  Slack (messages)...     ████████████████████ 1,204 messages ✓
  Fathom (transcripts)... ████████████████████  12 meetings  ✓

Processing...
  Cleaning & chunking...  ████████████████████ 3,847 chunks  ✓
  Generating embeddings...████████████████████ 3,847/3,847   ✓
  Detecting commitments...████████████████████ 23 found      ✓

Import complete!
  Documents: 1,586 ingested
  Commitments detected: 23 (14 pending, 6 completed, 3 unclear)
  Knowledge base ready for queries.

Would you like to review the detected commitments? [y/n]
> y

Pending commitments found:

  #  Priority  Commitment                          Owner          Due
  1  P1        Send investor deck v2               you            Apr 18
  2  P1        Review Laura's partnership proposal  you            Apr 15 (OVERDUE)
  3  P2        Share API docs with Bob              bob@partner.co Apr 20
  ...

[a] Accept all  [r] Review one by one  [d] Dismiss all  [s] Skip for now
> r
```

**Acciones backend:**
1. Para cada plataforma conectada:
   - `POST /ingest/sync/{platform}` con `since` calculado según la opción elegida
2. `GET /commitments/filter/pending` → mostrar compromisos detectados
3. El usuario puede:
   - Confirmar cada commitment (mantener status `pending`)
   - Marcar como completado: `PATCH /commitments/{id}` con `status: completed`
   - Descartar: `DELETE /commitments/{id}`

**Progress feedback:**
- Usar progress bars en terminal (via `rich` o similar)
- Mostrar contadores en tiempo real durante el sync
- Si una plataforma falla, continuar con las demás y reportar al final

#### Paso 5: Preferencias de Interacción Recurrente

```
━━━ Step 5/5: Your Daily Routine ━━━

Let's set up how I'll keep you informed.

Daily Briefing — a morning summary of your day ahead.
  What time should I send it? (24h format, your timezone)
> 07:30

What should the briefing include?
  [x] Today's agenda (calendar)
  [x] Pending commitments
  [x] Overdue items
  [x] Contextual alerts (meeting + commitment cross-reference)
  [ ] Yesterday's summary
  
Toggle with number, Enter to confirm:
> 5
  [x] Yesterday's summary

Commitment alerts — should I flag new commitments as I detect them?
  [1] Yes, immediately in chat
  [2] Only in the daily briefing
  [3] No alerts, I'll check manually

> 1

Weekly digest — a summary of your week every Friday?
  [y/n]
> y

Setup complete! Here's your configuration:

  Daily briefing: 07:30 AM (America/Argentina/Buenos_Aires)
  Commitment alerts: Immediate
  Weekly digest: Fridays

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You're all set, Mariano! 🎉

Your secondBrain is now active with:
  • 3 platforms connected
  • 1,586 documents in your knowledge base
  • 14 pending commitments tracked
  • Daily briefing at 07:30

You can start chatting now. Try:
  "What's on my plate today?"
  "Summarize my last call with Bob"
  "What did I promise this week?"

Type /help for all commands.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

you>
```

**Acciones backend:**
- `POST /briefing/{user_id}/schedule` con hora y timezone
- Guardar preferencias en config local + Identity/heuristics

---

### 2. Uso Diario — Chat Post-Onboarding

Una vez completado el onboarding, el CLI se convierte en un chat interactivo.

#### Interacción Principal: Queries en Lenguaje Natural

```
you> What meetings do I have today?

Checking your calendar and commitments...

Today's Schedule (April 17, 2026):

  09:00  Team Standup (with: alice, bob, laura)
  11:00  1:1 with Laura — RE: Partnership deal
         ⚠ Alert: You promised Laura to review her proposal (OVERDUE since Apr 15)
  14:00  Investor call with Fund ABC
         ⚠ Alert: Investor deck v2 due tomorrow (Apr 18)

  3 pending commitments relevant to today's meetings.
```

#### Comandos del Chat

| Comando | Descripción |
|---|---|
| `/briefing` | Generar briefing ahora |
| `/commitments` | Listar compromisos pendientes |
| `/overdue` | Listar compromisos vencidos |
| `/sync` | Sincronizar todas las plataformas |
| `/sync slack` | Sincronizar una plataforma específica |
| `/connect` | Conectar una nueva plataforma |
| `/disconnect <platform>` | Desconectar una plataforma |
| `/status` | Estado de conexiones y última sincronización |
| `/identity` | Ver/editar perfil y estilo |
| `/settings` | Preferencias de briefing y alertas |
| `/help` | Mostrar ayuda |
| `/quit` | Salir |

#### Alertas Proactivas

Cuando el sistema detecta nuevos compromisos durante un sync periódico:

```
━━━ New commitment detected ━━━
Source: Slack #engineering (just now)
"I'll have the architecture doc ready by Monday" — you

  Commitment: Prepare architecture document
  Due: Monday, April 21
  Priority: P2

[a] Accept  [e] Edit  [d] Dismiss
> a

Tracked! I'll remind you Sunday evening.
```

---

### 3. Re-onboarding y Mantenimiento

Si el usuario quiere agregar una plataforma o modificar su configuración después del onboarding inicial:

```
you> /connect

Which platform would you like to connect?
  [1] Microsoft Teams (not connected)

  Already connected:
    Outlook ✓ (last sync: 2h ago)
    Slack ✓ (last sync: 1h ago)
    Fathom ✓ (last sync: 3h ago)

> 1

[Inicia flujo de conexión para Teams]
```

```
you> /identity

Current profile:
  Role: CTO at a startup
  Tone: Direct, no-fluff, action-oriented
  Rules: 3 active

What would you like to change?
  [1] Role description
  [2] Tone guidelines
  [3] Rules/heuristics
  [4] Everything from scratch
  [b] Back

> 3

Current rules:
  1. Investor meetings = top priority
  2. "Urgent" = same-day
  3. Laura (co-founder) = sales

[a] Add a rule  [d] Delete a rule  [b] Back
> a

New rule:
> Bob from PartnerCo is our main technical contact

Added! 4 rules active.
```

---

## 🛠️ Especificación Técnica

### Dependencias Nuevas

| Paquete | Uso |
|---|---|
| `rich` | Formato de terminal: colores, tablas, progress bars, markdown, panels |
| `prompt_toolkit` | Input avanzado: autocompletado, historial, key bindings |

### Estructura de Archivos

```
cli/
├── __init__.py
├── __main__.py           # Entry point: python -m cli
├── main.py               # Inicialización, argparse, event loop
├── chat.py               # ChatSession: loop principal, historial
├── onboarding.py         # OnboardingFlow: wizard 5 pasos
├── commands.py           # CommandRouter: dispatch /commands
├── api_client.py         # APIClient: httpx async wrapper
├── display.py            # Formato: rich console, spinners, panels
├── config.py             # Config local: ~/.secondbrain/config.json
└── prompts.py            # Textos y mensajes del CLI
```

### Configuración Local

```json
// ~/.secondbrain/config.json
{
  "server_url": "http://localhost:8000",
  "user_id": "uuid-del-usuario",
  "user_name": "Mariano",
  "onboarding_completed": true,
  "onboarding_step": 5,
  "preferences": {
    "briefing_time": "07:30",
    "briefing_timezone": "America/Argentina/Buenos_Aires",
    "commitment_alerts": "immediate",
    "weekly_digest": true,
    "briefing_sections": ["agenda", "pending", "overdue", "alerts", "yesterday"]
  },
  "integrations": {
    "outlook": {"connected": true, "last_sync": "2026-04-17T10:00:00Z"},
    "slack": {"connected": true, "last_sync": "2026-04-17T11:00:00Z"},
    "fathom": {"connected": true, "last_sync": "2026-04-17T09:00:00Z"},
    "teams": {"connected": false}
  }
}
```

### API Endpoints Nuevos Requeridos

| Endpoint | Método | Descripción |
|---|---|---|
| `POST /users/{user_id}/identity` | POST | Crear Identity (persona, tono, heurísticas) |
| `PATCH /users/{user_id}/identity` | PATCH | Actualizar Identity |
| `GET /users/{user_id}/identity` | GET | Obtener Identity actual |
| `POST /ingest/sync/{platform}?since={iso_date}` | POST | Sync con fecha de inicio explícita (para import inicial) |
| `GET /users/{user_id}/stats` | GET | Estadísticas: docs totales, commitments, integraciones |

### Modelo de Estado del Onboarding

```python
@dataclass
class OnboardingState:
    """Persisted state for resumable onboarding."""
    current_step: int = 0          # 0-5
    user_created: bool = False
    platforms_connected: List[str] = field(default_factory=list)
    identity_configured: bool = False
    initial_import_done: bool = False
    preferences_set: bool = False
```

Si el usuario cierra el CLI a mitad del onboarding, al volver se resume desde el último paso completado.

### Sync Periódico en Background

El CLI puede correr un sync periódico en background mientras el usuario chatea:

```python
async def background_sync_loop(api: APIClient, interval_minutes: int = 30) -> None:
    """Sync all connected platforms periodically."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        for platform in connected_platforms:
            result = await api.sync_platform(platform)
            if result.commitments_detected > 0:
                # Push alert to chat
                display_new_commitments(result)
```

---

## 📋 Criterios de Aceptación

### Onboarding
- [ ] El usuario puede crear cuenta desde el CLI
- [ ] Puede conectar 1+ plataformas con validación de token
- [ ] Tokens inválidos muestran error claro con sugerencias
- [ ] Puede saltar pasos y volver después
- [ ] El onboarding se resume si se cierra a mitad
- [ ] El import inicial muestra progreso en tiempo real
- [ ] Los commitments detectados se pueden revisar y aceptar/rechazar
- [ ] La identidad y estilo se configuran conversacionalmente
- [ ] Las preferencias de briefing se persisten

### Chat Diario
- [ ] Queries en lenguaje natural funcionan via `/agent/query`
- [ ] Los comandos `/` ejecutan acciones específicas
- [ ] Las alertas proactivas se muestran cuando se detectan nuevos commitments
- [ ] El sync periódico corre en background
- [ ] El historial del chat se mantiene en la sesión

### Mantenimiento
- [ ] Puede agregar/remover plataformas post-onboarding
- [ ] Puede editar identidad y preferencias
- [ ] `/status` muestra estado actualizado de todas las conexiones
- [ ] La configuración local persiste entre sesiones

### UX
- [ ] Output formateado con colores, tablas, y panels (via `rich`)
- [ ] Progress bars durante syncs largos
- [ ] Spinners durante operaciones async
- [ ] Mensajes de error claros con next steps
- [ ] Historial de input navegable con flechas (via `prompt_toolkit`)
- [ ] Autocompletado de comandos `/`

---

## 🔄 Fases de Implementación

### Fase 7A: CLI Foundation + Onboarding
- `cli/main.py`, `cli/config.py`, `cli/display.py`, `cli/api_client.py`
- `cli/onboarding.py` — los 5 pasos del wizard
- Endpoints nuevos: Identity CRUD, stats
- Tests: unit (onboarding flow), integration (API client), e2e (full onboarding)

### Fase 7B: Chat Diario + Comandos
- `cli/chat.py`, `cli/commands.py`
- Routing de queries a `/agent/query` o `/query`
- Comandos `/briefing`, `/commitments`, `/sync`, etc.
- Background sync loop
- Tests: unit (command routing), integration (chat session), e2e (full conversation)

### Fase 7C: Alertas Proactivas + Polish
- Sistema de alertas en tiempo real desde background sync
- Manejo de re-onboarding (`/connect`, `/identity`, `/settings`)
- UX polish: autocompletado, historial, colores consistentes
- Tests: e2e (alerta flow), UX testing manual

---

## 🔍 Decisiones de Diseño

| Decisión | Alternativa | Razón |
|---|---|---|
| CLI/terminal como interfaz MVP | Web app | Más rápido de implementar, cero dependencias de frontend, ideal para usuario técnico, se puede evolucionar a web después |
| `rich` para formato | `click`/`typer` | `rich` tiene soporte nativo de markdown, tablas, panels, progress bars, colores — todo lo que necesitamos |
| `prompt_toolkit` para input | `input()` nativo | Historial, autocompletado, key bindings — UX profesional |
| Token manual (no OAuth redirect) | Browser redirect flow | MVP simplicity — OAuth redirect requiere servidor de callback, estado, browser automation. Tokens manuales son suficientes para single-user |
| Config en `~/.secondbrain/` | En el proyecto | La config del CLI es personal, no del proyecto. Incluir server URL permite apuntar a diferentes backends |
| Sync periódico in-process | Celery/cron externo | Suficiente para MVP single-user. El CLI corre todo el día como un "copilot" en la terminal |
| Onboarding resumable | One-shot | El usuario puede cerrar la terminal a mitad del setup. Guardar estado evita frustración |
