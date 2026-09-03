---
name: Containerization/Deployment Review
description: Phase 4 containerization review -- port binding, shell injection, Python version mismatch, CORS wildcards broken, no .dockerignore
type: project
---

Containerization + Deployment review completed 2026-04-19. Key findings:

- Docker port binding `8000:8000` exposes unauthenticated API on all interfaces; Docker bypasses host firewall (UFW/iptables). Must bind `127.0.0.1:8000:8000`.
- Shell variable `${DATABASE_URL_SYNC}` interpolated into Python string in docker-entrypoint.sh -- injection vector + quoting bug. Use `os.environ` instead.
- Dockerfile uses Python 3.11 but project documents Python 3.8. Needs alignment or documentation update.
- Starlette CORSMiddleware does not support glob patterns like `http://localhost:*` -- these silently fail to match.
- `/health/detailed` exposes database errors and env info without authentication.
- No `.dockerignore` -- build context includes .env, .git, tests.
- Healthchecks (Dockerfile + compose + deploy.sh) all hit `/` which is always-200, not the DB-checking `/health/detailed`.
- No old image pruning in deploy.sh -- free-tier VM disk will fill.

**Why:** This is a personal tool behind Tailscale, but Docker's iptables manipulation is a well-known footgun that bypasses UFW. No-auth API + public port = full access for anyone on the same network.

**How to apply:** In future infra reviews, always verify: (1) port bindings are localhost-only when behind a reverse proxy, (2) shell scripts never interpolate env vars into code strings, (3) health endpoints used in orchestration actually test real dependencies.
