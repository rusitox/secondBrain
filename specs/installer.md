# Spec: Instalador de secondBrain

## Objetivo

Un instalador cross-platform (macOS + Windows) que deje el producto 100% funcional: instala dependencias del sistema, levanta la base de datos, configura el entorno, arranca el backend, y fluye directamente al onboarding existente. El usuario pasa de cero a usando el producto en un solo comando.

---

## Flujo Completo

```
install.sh / install.ps1  (bootstrap mínimo)
       │
       ▼
[1] Verificar/instalar Python 3.8+
[2] Verificar/instalar Docker Desktop
[3] pip install -r requirements.txt
       │
       ▼
python -m cli install  (interactivo, con Rich)
       │
       ▼
[4] Verificar Docker corriendo
[5] Levantar PostgreSQL + pgvector (docker-compose)
[6] Esperar que DB esté lista
[7] Solicitar API keys (OpenAI, Claude)
[8] Generar Fernet key automáticamente
[9] Escribir .env
[10] Correr migraciones (alembic upgrade head)
[11] Arrancar backend como subprocess
[12] Verificar conectividad (health check)
       │
       ▼
Onboarding existente (5 pasos)
       │
       ▼
Chat diario listo
```

---

## Componentes

### 1. Bootstrap Scripts (platform-specific, mínimos)

#### `install.sh` (macOS / Linux)

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== secondBrain Installer ==="

# 1. Python
if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Installing via Homebrew..."
    if ! command -v brew &>/dev/null; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    brew install python@3.11
fi
echo "✓ Python $(python3 --version)"

# 2. Docker
if ! command -v docker &>/dev/null; then
    echo "Docker not found. Installing Docker Desktop..."
    brew install --cask docker
    echo "Please start Docker Desktop and re-run this script."
    exit 1
fi
echo "✓ Docker $(docker --version)"

# 3. Dependencies
python3 -m pip install -r requirements.txt --quiet

# 4. Delegate to CLI
python3 -m cli install
```

#### `install.ps1` (Windows / PowerShell)

```powershell
Write-Host "=== secondBrain Installer ===" -ForegroundColor Cyan

# 1. Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python via winget..."
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "✓ Python $(python --version)"

# 2. Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Docker Desktop via winget..."
    winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Write-Host "Please start Docker Desktop and re-run this script."
    exit 1
}
Write-Host "✓ Docker $(docker --version)"

# 3. Dependencies
python -m pip install -r requirements.txt --quiet

# 4. Delegate to CLI
python -m cli install
```

---

### 2. Docker Compose (`docker-compose.yml`)

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: secondbrain-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: secondbrain
      POSTGRES_USER: secondbrain
      POSTGRES_PASSWORD: ${DB_PASSWORD:-secondbrain_dev}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - secondbrain-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U secondbrain"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  secondbrain-data:
```

**Decisiones:**
- `pgvector/pgvector:pg16` — imagen oficial con pgvector preinstalado
- Volume named para persistir datos entre reinicios
- Healthcheck para que el installer pueda esperar a que esté lista
- Puerto configurable vía `DB_PORT` env var (evita conflictos si el usuario ya tiene un postgres local)

---

### 3. CLI Install Command (`cli/installer.py`)

Nuevo módulo que maneja toda la instalación interactiva desde Python.

```python
class Installer:
    """Interactive installer for secondBrain."""

    async def run(self) -> bool:
        """Run the full installation flow. Returns True if successful."""
        # Step 1: Check Docker
        # Step 2: Start database
        # Step 3: Collect API keys
        # Step 4: Generate config
        # Step 5: Run migrations
        # Step 6: Start backend
        # Step 7: Health check
        # Returns True → main.py continues to onboarding
```

#### Step 1: Verificar Docker

```
━━━ secondBrain Installation ━━━

Checking prerequisites...

  Docker:   ✓ Running (Docker Desktop 4.x)
  Database: ○ Not set up yet
  Backend:  ○ Not running
```

Si Docker no está corriendo:
```
  Docker:   ✗ Not running

  Docker Desktop is installed but not running.
  Please start Docker Desktop and press Enter to continue.

  [Enter] Retry  [q] Quit
```

#### Step 2: Levantar Base de Datos

```
Setting up PostgreSQL + pgvector...

  Pulling image pgvector/pgvector:pg16... ████████████████ done
  Starting container secondbrain-db...    ████████████████ done
  Waiting for database...                 ████████████████ ready

  Database: ✓ Running on localhost:5432
```

Implementación:
- Correr `docker compose up -d` desde Python (subprocess)
- Esperar healthcheck con polling (max 30 segundos)
- Si el puerto 5432 está ocupado, probar 5433, 5434... y guardar el puerto usado
- Si ya existe el container `secondbrain-db`, verificar que esté corriendo y reusar

#### Step 3: Solicitar API Keys

```
━━━ API Configuration ━━━

secondBrain uses OpenAI for embeddings and Claude for AI reasoning.

OpenAI API Key (for embeddings):
  Get one at: https://platform.openai.com/api-keys
  > sk-••••••••••••••••••••••••

  Validating... ✓ Valid (organization: Personal)

Claude API Key (for AI reasoning):
  Get one at: https://console.anthropic.com/settings/keys
  > sk-ant-••••••••••••••••••••

  Validating... ✓ Valid
```

- Input con `password=True` (oculta la key)
- Validación: llamada ligera a cada API para verificar que la key funciona
  - OpenAI: `GET /v1/models` con la key
  - Claude: `GET /v1/models` o un mensaje mínimo
- Si falla: error claro + retry/skip
- Skip allowed para Claude (commitment detection y briefing no funcionarán, pero RAG con embeddings sí)

#### Step 4: Generar Configuración

```
Generating configuration...

  Fernet encryption key: ✓ Generated
  Environment file:      ✓ Written to .env
  CLI config:            ✓ Written to ~/.secondbrain/config.json
```

- Generar `FERNET_KEY` automáticamente con `Fernet.generate_key()`
- Escribir `.env` con todos los valores (DB URL con puerto correcto, API keys, Fernet key)
- No sobrescribir `.env` existente — preguntar: `[o] Overwrite  [m] Merge  [k] Keep existing`
- Escribir/actualizar `~/.secondbrain/config.json` con `server_url`

#### Step 5: Migraciones

```
Running database migrations...

  Applying migrations... ████████████████ done
  Tables created: users, identities, integrations, documents, commitments
  pgvector extension: ✓ Enabled

  Database: ✓ Schema ready
```

- Correr `alembic upgrade head` como subprocess
- Si falla: mostrar error de Alembic limpio, no el stacktrace completo

#### Step 6: Arrancar Backend

```
Starting secondBrain backend...

  Server starting on http://localhost:8000... ████████ done
  Health check: ✓ API responding

  Backend: ✓ Running (PID 12345)
```

- Arrancar `uvicorn app.main:app` como subprocess en background
- Guardar PID en `~/.secondbrain/server.pid` para poder pararlo después
- Redirigir stdout/stderr a `~/.secondbrain/server.log`
- Esperar health check (`GET /health`) con polling (max 15 segundos)
- Si el puerto 8000 está ocupado: probar 8001, 8002... y actualizar config

#### Step 7: Resumen y Transición a Onboarding

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Installation Complete!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Database:  PostgreSQL 16 + pgvector (Docker)
  Backend:   http://localhost:8000 (PID 12345)
  Config:    ~/.secondbrain/config.json

  Now let's set up your account and connect your platforms.
  Press Enter to continue...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ Step 1/5: Welcome ━━━
  [El onboarding existente continúa desde acá]
```

---

### 4. Server Management en el CLI

Además del install, el CLI necesita gestionar el ciclo de vida del backend.

#### Auto-start en `cli/main.py`

Cuando el usuario corre `python -m cli` (sin `install`) y el backend no responde, el CLI intenta levantarlo automáticamente:

```python
# En async_main(), reemplazar el bloque actual de error de conectividad:
if not connected:
    if await _can_autostart():
        print_info("Backend not running. Starting it...")
        started = await _start_backend(config)
        if started:
            connected = await api.health_check()

    if not connected:
        print_error("Cannot reach backend...")
        return 1
```

`_can_autostart()` verifica:
1. Que exista `.env` (indica que install se completó)
2. Que Docker esté corriendo
3. Que el container `secondbrain-db` exista y esté corriendo

#### Módulo `cli/server.py`

```python
class ServerManager:
    """Manages the backend server lifecycle."""

    PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
    LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"

    async def start(self) -> bool:
        """Start the backend server as a background process."""

    async def stop(self) -> bool:
        """Stop the backend server."""

    def is_running(self) -> bool:
        """Check if the server process is still alive."""

    async def ensure_db_running(self) -> bool:
        """Check and start the Docker database if needed."""

    async def health_check(self, timeout: float = 15.0) -> bool:
        """Poll health endpoint until ready."""
```

#### Nuevos Slash Commands

| Comando | Acción |
|---|---|
| `/server start` | Arrancar backend (si no está corriendo) |
| `/server stop` | Parar backend + DB |
| `/server restart` | Restart backend |
| `/server status` | Mostrar estado de backend + DB |
| `/server logs` | Mostrar últimas líneas del log del server |

---

### 5. Manejo de Re-instalación y Upgrades

Si el usuario corre `python -m cli install` cuando ya está instalado:

```
secondBrain is already installed.

  Database:  ✓ Running (secondbrain-db)
  Backend:   ✓ Running (PID 12345)
  Config:    ✓ ~/.secondbrain/config.json

What would you like to do?

  [r] Reinstall from scratch (deletes all data)
  [u] Update (pull latest DB image, re-run migrations)
  [c] Reconfigure (API keys, server settings)
  [q] Cancel

> u

Updating...
  Pulling latest pgvector image... done
  Running migrations... done (no new migrations)

  ✓ Updated successfully.
```

---

## Archivos a Crear/Modificar

### Nuevos

| Archivo | Descripción |
|---|---|
| `install.sh` | Bootstrap script para macOS/Linux |
| `install.ps1` | Bootstrap script para Windows |
| `docker-compose.yml` | PostgreSQL + pgvector container |
| `cli/installer.py` | `Installer` class — flujo de instalación interactivo |
| `cli/server.py` | `ServerManager` class — start/stop/status del backend |
| `tests/unit/test_installer.py` | Tests del installer (mocking subprocess/docker) |
| `tests/unit/test_server_manager.py` | Tests del server manager |

### Modificar

| Archivo | Cambios |
|---|---|
| `cli/main.py` | Agregar subcomando `install`, auto-start del backend |
| `cli/commands.py` | Agregar comandos `/server` |
| `cli/config.py` | Agregar campos: `db_port`, `server_port`, `server_pid` |
| `requirements.txt` | (sin cambios — `httpx`, `rich`, `prompt_toolkit` ya están) |

---

## Decisiones de Diseño

| Decisión | Alternativa | Razón |
|---|---|---|
| Docker para PostgreSQL | Instalación nativa | Cross-platform (macOS + Windows), aislado, reproducible, pgvector preinstalado |
| `pgvector/pgvector:pg16` | Build propio | Imagen oficial, mantenida, PG16 estable |
| Bootstrap en bash/ps1 + CLI en Python | Todo en bash | El bash solo instala Python+Docker (mínimo). El CLI con Rich da UX profesional cross-platform |
| Backend como subprocess del CLI | Servicio del sistema | Más simple, no requiere permisos de admin, el CLI lo controla todo |
| Puerto auto-discovery | Puerto fijo | Evita conflictos si el usuario ya tiene postgres/servicios en 5432/8000 |
| API key validation en install | Solo guardar | Detecta errores temprano, evita frustración en el primer query |
| Fernet key auto-generada | Pedírsela al usuario | Es un detalle interno, no tiene sentido exponerlo |
| `.env` merge vs overwrite | Siempre overwrite | El usuario puede tener keys que no quiere perder |

---

## Consideraciones de Seguridad

- Las API keys se ingresan con `password=True` (no se ven en pantalla)
- `.env` se crea con permisos `0o600` (solo el usuario puede leerlo)
- Las credenciales de la DB en Docker son para desarrollo local — producción usaría Supabase
- El `server.pid` permite parar el backend limpiamente
- Los logs del server se guardan en `~/.secondbrain/server.log` (no en el directorio del proyecto)

---

## Fases de Implementación

### Fase 8A: Docker + Installer Core
- `docker-compose.yml`
- `cli/installer.py` (steps 1-5: Docker, DB, API keys, config, migrations)
- `cli/server.py` (start/stop/health check)
- Tests unitarios

### Fase 8B: Bootstrap Scripts + Integration
- `install.sh` + `install.ps1`
- Modificar `cli/main.py` (subcomando `install`, auto-start)
- Modificar `cli/commands.py` (comandos `/server`)
- Modificar `cli/config.py` (nuevos campos)
- Tests de integración

### Fase 8C: Re-instalación, Upgrades, Edge Cases
- Manejo de reinstall/update/reconfigure
- Puerto auto-discovery (conflictos)
- Manejo de `.env` existente (merge)
- Robustez: Docker no arranca, puerto ocupado, migración falla
- Tests de edge cases

---

## Criterios de Aceptación

### Install (happy path)
- [ ] `./install.sh` en macOS instala Python, Docker, deps, y fluye al CLI install
- [ ] `install.ps1` en Windows hace lo equivalente
- [ ] `python -m cli install` levanta DB en Docker, pide API keys, configura .env, corre migraciones, arranca backend, y pasa al onboarding
- [ ] El onboarding existente funciona sin cambios después del install
- [ ] Después del install + onboarding, `python -m cli` arranca directo al chat

### Server management
- [ ] `python -m cli` auto-levanta el backend si no está corriendo (post-install)
- [ ] `/server status` muestra estado de backend + DB
- [ ] `/server stop` para todo limpiamente
- [ ] `/server start` lo levanta de nuevo

### Edge cases
- [ ] Puerto 5432 ocupado → usa otro puerto automáticamente
- [ ] Puerto 8000 ocupado → usa otro puerto automáticamente
- [ ] Docker no instalado → mensaje claro con instrucciones
- [ ] Docker no corriendo → mensaje claro pidiendo arrancar Docker Desktop
- [ ] API key inválida → error + retry/skip
- [ ] `.env` ya existe → pregunta merge/overwrite/keep
- [ ] Re-run de install → detecta instalación existente, ofrece opciones
- [ ] Container DB ya existe → reusa, no duplica
