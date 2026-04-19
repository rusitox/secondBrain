# Deploy secondBrain to Oracle Cloud VPS

Paso a paso para deployar secondBrain en la VM de Oracle Cloud (ARM) con Tailscale.

**Prerequisitos ya cumplidos:**
- VM Oracle Cloud free-tier ARM provisionada
- Docker Engine + Docker Compose instalados
- Tailscale conectado (la VM ya corre familyhub)
- Nginx instalado (compartido con familyhub)
- GitHub Actions configurado (self-hosted runner en la VM)

---

## Paso 1: Preparar el directorio en la VM

```bash
ssh oracle-vm

# Crear directorio de la app
sudo mkdir -p /opt/secondbrain
sudo chown $USER:$USER /opt/secondbrain
cd /opt/secondbrain
```

## Paso 2: Copiar archivos de configuracion

Desde tu maquina local:

```bash
cd ~/Documents/Code/secondBrain

# Copiar compose y configs
scp docker-compose.prod.yml oracle-vm:/opt/secondbrain/
scp .env.prod.example oracle-vm:/opt/secondbrain/
scp infra/backup.sh oracle-vm:/opt/secondbrain/
scp infra/secondbrain.service oracle-vm:/opt/secondbrain/
```

## Paso 3: Crear el .env.prod

```bash
ssh oracle-vm
cd /opt/secondbrain

cp .env.prod.example .env.prod
```

Editar `.env.prod` con tus valores:

```bash
nano .env.prod
```

```env
APP_ENV=production

# Password fuerte para PostgreSQL
DB_PASSWORD=<generar-password-seguro>

# Mismo FERNET_KEY que tu .env local (para no perder tokens encriptados)
FERNET_KEY=<copiar-de-tu-.env-local>

# API keys
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...
```

Para generar un password seguro:
```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Asegurar permisos:
```bash
chmod 600 .env.prod
```

## Paso 4: Configurar GHCR login en la VM

El self-hosted runner ya tiene acceso via `GITHUB_TOKEN`, pero para pulls manuales:

```bash
ssh oracle-vm

# Login a GHCR (usar un Personal Access Token con scope packages:read)
echo "ghp_TU_TOKEN" | docker login ghcr.io -u rusitox --password-stdin
```

## Paso 5: Primer build y deploy

Opcion A: **Dejar que GitHub Actions haga el build** (recomendado)

Push a main dispara el workflow. Si el self-hosted runner esta configurado, despliega automaticamente.

Opcion B: **Deploy manual** la primera vez

```bash
ssh oracle-vm
cd /opt/secondbrain

# Pull la imagen (ya buildeada por GitHub Actions)
docker pull ghcr.io/rusitox/secondbrain:latest

# Levantar DB primero
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db

# Esperar que la DB este lista (~10s)
sleep 10

# Correr migrations
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm api alembic upgrade head

# Levantar todo
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# Verificar
docker compose -f docker-compose.prod.yml ps
curl -s http://localhost:8000/health/detailed | python3 -m json.tool
```

## Paso 6: Configurar nginx

```bash
ssh oracle-vm

# Copiar config de nginx
sudo cp /opt/secondbrain/infra/nginx/secondbrain.conf /etc/nginx/sites-enabled/secondbrain.conf

# Nota: si no existe sites-enabled, puede ser conf.d:
# sudo cp secondbrain.conf /etc/nginx/conf.d/secondbrain.conf

# Verificar sintaxis
sudo nginx -t

# Recargar
sudo nginx -s reload
```

Esto expone la API en el puerto **8080** via nginx. Desde cualquier dispositivo en el tailnet:

```bash
curl http://oracle-vm:8080/health/detailed
```

## Paso 7: Migrar datos locales (opcional)

Si tenes datos en tu PostgreSQL local que queres llevar al server:

```bash
# En tu maquina local: exportar
docker exec secondbrain-db pg_dump -U secondbrain secondbrain > local-backup.sql

# Copiar al server
scp local-backup.sql oracle-vm:/tmp/

# En el server: importar
ssh oracle-vm
docker exec -i secondbrain-db psql -U secondbrain secondbrain < /tmp/local-backup.sql

# Limpiar
rm /tmp/local-backup.sql
```

**Importante:** Usa el mismo `FERNET_KEY` en `.env.prod` que en tu `.env` local. Si cambias la key, los tokens encriptados de las integraciones quedan ilegibles y hay que reconectar todo.

## Paso 8: Crear API key

```bash
ssh oracle-vm
cd /opt/secondbrain

# Primero, buscar tu user_id
docker exec secondbrain-api python3 -c "
import asyncio
from sqlalchemy import select
from app.core.database import get_session_factory
from app.models.user import User
async def main():
    sf = get_session_factory()
    async with sf() as db:
        result = await db.execute(select(User))
        for u in result.scalars():
            print(f'{u.id}  {u.full_name}  {u.email}')
asyncio.run(main())
"

# Crear API key (reemplazar UUID con tu user_id)
docker exec -it secondbrain-api python3 -m app.cli.create_api_key \
  --user-id <TU-UUID> \
  --name "macbook"
```

Copiar la key que aparece (empieza con `sb_live_`). No se puede recuperar despues.

## Paso 9: Login desde el CLI

En cualquier maquina con el CLI instalado:

```bash
# Si tenes el repo clonado
cd ~/Documents/Code/secondBrain
python -m cli login

# O si instalaste solo el CLI
secondbrain login
```

Ingresar:
- Server URL: `http://oracle-vm:8080`
- API key: `sb_live_...` (la que copiaste en el paso 8)

Verificar:
```bash
python -m cli
# Deberia conectar y mostrar el chat
```

## Paso 10: Configurar systemd (auto-start on reboot)

```bash
ssh oracle-vm

sudo cp /opt/secondbrain/secondbrain.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable secondbrain
sudo systemctl start secondbrain

# Verificar
sudo systemctl status secondbrain
```

## Paso 11: Configurar backup diario

```bash
ssh oracle-vm
cd /opt/secondbrain

# Crear directorio de backups
mkdir -p /opt/secondbrain/backups

# Hacer ejecutable
chmod +x backup.sh

# Agregar al crontab (backup a las 3am)
crontab -e
# Agregar esta linea:
# 0 3 * * * /opt/secondbrain/backup.sh >> /opt/secondbrain/backups/backup.log 2>&1

# Test manual
./backup.sh
```

## Paso 12: Configurar self-hosted runner (para CI/CD automatico)

Si el runner ya esta corriendo para familyhub, hay que verificar que tenga acceso al repo de secondBrain.

```bash
ssh oracle-vm

# Verificar que el runner esta activo
cd ~/actions-runner  # o donde este instalado
./svc.sh status
```

En GitHub: Settings > Actions > Runners > verificar que el runner aparece como "Online".

En el repo secondBrain: Settings > Environments > crear "production" si no existe.

---

## Verificacion final

Desde tu maquina local:

```bash
# 1. Health check via nginx
curl http://oracle-vm:8080/health/detailed

# 2. Login con CLI
python -m cli login
# URL: http://oracle-vm:8080
# API key: sb_live_...

# 3. Iniciar chat
python -m cli
# Deberia conectar, sincronizar estado, y mostrar el prompt

# 4. Verificar sync
# En el chat:
/status
/sync
```

---

## Troubleshooting

```bash
ssh oracle-vm
cd /opt/secondbrain

# Ver logs de la API
docker compose -f docker-compose.prod.yml logs api --tail 100

# Ver logs de la DB
docker compose -f docker-compose.prod.yml logs db --tail 50

# Reiniciar todo
docker compose -f docker-compose.prod.yml --env-file .env.prod restart

# Rebuild forzado (si la imagen esta corrupta)
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# Entrar al container de la API
docker exec -it secondbrain-api bash

# Entrar a la DB
docker exec -it secondbrain-db psql -U secondbrain secondbrain
```

---

## Arquitectura final

```
[Tu Mac/PC]                    [Oracle Cloud VM (ARM)]
                                    via Tailscale
python -m cli ──HTTP──> nginx:8080 ──> secondbrain-api:8000
                                              │
                                    secondbrain-db (PostgreSQL+pgvector)
                                              │
                                    /opt/secondbrain/backups (daily pg_dump)
```

GitHub Actions: push to main → build image → GHCR → self-hosted runner pulls + deploys.
