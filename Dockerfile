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
