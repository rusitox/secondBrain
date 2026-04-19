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
docker compose -f docker-compose.prod.yml pull
echo "Restarting services..."
docker compose -f docker-compose.prod.yml up -d
echo "Pruning old images..."
docker image prune -f
echo "Waiting for health check..."
sleep 5
if curl -sf http://localhost:8000/ > /dev/null; then
    echo "Deployment successful!"
else
    echo "WARNING: Health check failed. Check logs with:"
    echo "  docker compose -f docker-compose.prod.yml logs api"
    exit 1
fi
EOF
