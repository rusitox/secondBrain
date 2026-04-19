#!/bin/bash
set -e

# PostgreSQL backup for secondBrain
#
# Cron: 0 3 * * * /opt/secondbrain/infra/backup.sh
# Keeps last 30 days of backups.

BACKUP_DIR="/opt/secondbrain/backups"
CONTAINER="secondbrain-db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="secondbrain_${TIMESTAMP}.sql.gz"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "Starting backup..."
docker exec "$CONTAINER" pg_dump -U secondbrain secondbrain | gzip > "$BACKUP_DIR/$FILENAME"

SIZE=$(du -h "$BACKUP_DIR/$FILENAME" | cut -f1)
echo "Backup created: $FILENAME ($SIZE)"

# Clean old backups
DELETED=$(find "$BACKUP_DIR" -name "secondbrain_*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "Deleted $DELETED backup(s) older than $RETENTION_DAYS days"
fi

# Disk usage warning
USAGE=$(df "$BACKUP_DIR" --output=pcent 2>/dev/null | tail -1 | tr -d ' %' || echo "0")
if [ "$USAGE" -gt 80 ] 2>/dev/null; then
    echo "WARNING: Disk usage at ${USAGE}%"
fi

echo "Backup complete"
