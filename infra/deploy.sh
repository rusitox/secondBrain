#!/bin/bash
set -e

# Deploy secondBrain to Oracle Cloud VM via Tailscale
#
# Usage:
#   ./infra/deploy.sh                        # uses default host
#   ./infra/deploy.sh --host my-oracle-vm    # custom Tailscale hostname

HOST="${SECONDBRAIN_DEPLOY_HOST:-oracle-vm}"
REMOTE_DIR="/opt/secondbrain"

while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            HOST="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Deploying to $HOST..."

# Pull latest image and restart
ssh "$HOST" bash -s <<EOF
cd $REMOTE_DIR
echo "Pulling latest image..."
docker pull ghcr.io/rusitox/secondbrain:latest
echo "Running migrations..."
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api alembic upgrade head
echo "Restarting services..."
IMAGE_TAG=latest docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api db
echo "Pruning old images..."
docker image prune -f
echo "Waiting for health check..."
sleep 10
if curl -sf http://localhost:8000/health/detailed | grep -q '"status":"healthy"'; then
    echo "Deployment successful!"
else
    echo "WARNING: Health check failed. Check logs with:"
    echo "  docker compose -f docker-compose.prod.yml logs api"
    exit 1
fi
EOF
