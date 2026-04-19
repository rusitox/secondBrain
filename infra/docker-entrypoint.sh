#!/bin/bash
set -e

echo "Waiting for database..."
retries=0
max_retries=30
until python -c "
import os, sys
try:
    import psycopg2
    conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
    conn.close()
except Exception as e:
    print(f'DB not ready: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
    retries=$((retries + 1))
    if [ "$retries" -ge "$max_retries" ]; then
        echo "ERROR: Database not reachable after $max_retries attempts"
        exit 1
    fi
    echo "Waiting for database... ($retries/$max_retries)"
    sleep 2
done

echo "Database is ready"

echo "Running migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
