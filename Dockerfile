# Stage 0: Frontend build (MAREA — see frontend/vite.config.ts)
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
# vite.config.ts's outDir "../static/marea" is relative to /frontend, so
# this lands at /static/marea — copied into the runtime image below.
RUN npm run build

# Stage 1: Build dependencies
FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
# static/ was never copied here before — app/main.py's mounts for
# /voice-ui and /marea were silently 404ing in every deployed image ("if
# os.path.isdir(...)" made the miss invisible; it now at least logs a
# warning). static/voice/ is hand-written and copied as-is; static/marea/
# is MAREA's build output from the frontend-builder stage above.
COPY static/voice ./static/voice
COPY --from=frontend-builder /static/marea ./static/marea
COPY infra/docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh

# Set ownership
RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/health/detailed | grep -q '"status":"healthy"' || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
