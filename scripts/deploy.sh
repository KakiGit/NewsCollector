#!/usr/bin/env bash
#
# Deploy NewsCollector container to a remote machine via SSH
#
# Usage: ./scripts/deploy.sh <hostname>
#
# Prerequisites:
#   - SSH access to the remote host (preferably with key-based auth)
#   - Podman or Docker installed on the remote machine
#   - podman-compose or docker-compose installed on the remote machine

set -euo pipefail

# Configuration
REMOTE_DIR="vol_news_collector"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $* >&2"; }

usage() {
    echo "Usage: $0 <remote-host>"
    echo ""
    echo "Deploy NewsCollector container to a remote machine using podman-compose."
    echo ""
    echo "Arguments:"
    echo "  remote-host    SSH hostname or user@hostname"
    echo ""
    echo "Examples:"
    echo "  $0 myserver"
    echo "  $0 user@192.168.1.100"
    echo "  $0 user@myserver.example.com"
    exit 1
}

# Check arguments
if [[ $# -lt 1 ]]; then
    log_error "Missing required argument: remote host"
    usage
fi

REMOTE_HOST="$1"

# Verify required commands exist locally
for cmd in docker ssh rsync; do
    if ! command -v "$cmd" &> /dev/null; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done

# Verify SSH connectivity
log_info "Verifying SSH connectivity to ${REMOTE_HOST}..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_HOST" "exit 0" 2>/dev/null; then
    log_error "Cannot connect to ${REMOTE_HOST} via SSH"
    log_error "Make sure SSH key-based authentication is set up"
    exit 1
fi
log_ok "SSH connection verified"

# Render docker-compose.yml for remote deployment (without exposed ports)
log_info "Rendering docker-compose.yml for remote deployment..."
python3 scripts/render_docker_compose.py --remote
log_ok "docker-compose.yml rendered"

# Detect container runtime on remote (docker or podman)
log_info "Detecting container runtime on remote..."
if ssh "$REMOTE_HOST" "command -v podman" &> /dev/null; then
    REMOTE_CTR="podman"
    log_ok "Remote container runtime: Podman"
elif ssh "$REMOTE_HOST" "command -v docker" &> /dev/null; then
    REMOTE_CTR="docker"
    log_ok "Remote container runtime: Docker"
else
    log_error "Neither Docker nor Podman found on remote host"
    exit 1
fi

# Detect compose command on remote
log_info "Detecting compose command on remote..."
if ssh "$REMOTE_HOST" "command -v podman-compose" &> /dev/null; then
    COMPOSE_CMD="podman-compose"
    log_ok "Compose command: podman-compose"
elif ssh "$REMOTE_HOST" "command -v docker-compose" &> /dev/null; then
    COMPOSE_CMD="docker-compose"
    log_ok "Compose command: docker-compose"
elif ssh "$REMOTE_HOST" "$REMOTE_CTR compose version" &> /dev/null; then
    COMPOSE_CMD="$REMOTE_CTR compose"
    log_ok "Compose command: $REMOTE_CTR compose"
else
    log_error "No compose tool found on remote host (podman-compose, docker-compose, or $REMOTE_CTR compose)"
    exit 1
fi

# Check if remote needs initial setup
log_info "Checking if remote needs initial setup..."
if ! ssh "$REMOTE_HOST" "test -d ~/${REMOTE_DIR}" 2>/dev/null; then
    log_warn "Remote directory not found. Running setup first..."
    ./scripts/setup.sh "$REMOTE_HOST"
fi

# Transfer the project folder to remote using rsync
log_info "Syncing project folder to remote..."
rsync -e ssh --progress --archive --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude 'output' \
    --exclude '*.tar.gz' \
    . "${REMOTE_HOST}:~/${REMOTE_DIR}/"
log_ok "Project folder synced"

# Build the image on remote
log_info "Building Docker image on remote..."
ssh "$REMOTE_HOST" "cd ~/${REMOTE_DIR} && ${REMOTE_CTR} build -t newscollector:latest ."
log_ok "Image built successfully"

# Ensure the external network exists on remote
log_info "Ensuring shared-network exists on remote..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} network create shared-network 2>/dev/null || true"

# Stop existing containers (if running)
log_info "Stopping existing containers..."
ssh "$REMOTE_HOST" "cd ~/${REMOTE_DIR} && ${COMPOSE_CMD} down" 2>/dev/null || true
log_ok "Old containers stopped"

# Start the new containers with compose
log_info "Starting containers with podman-compose..."
ssh "$REMOTE_HOST" "cd ~/${REMOTE_DIR} && ${COMPOSE_CMD} up -d"
log_ok "Containers started successfully"

# Verify container is running
log_info "Verifying container status..."
if ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=newscollector --format '{{.Status}}'" | grep -q "Up"; then
    log_ok "Deployment complete! Container is running on ${REMOTE_HOST}"
    echo ""
    echo "Container details:"
    ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=newscollector --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
else
    log_error "Container may have failed to start. Check logs with:"
    echo "  ssh ${REMOTE_HOST} ${REMOTE_CTR} logs newscollector"
    exit 1
fi

echo ""
log_ok "Deployment successful!"
echo ""
echo "To access the web UI, open: http://${REMOTE_HOST}:8000"
echo ""
echo "Useful commands:"
echo "  ssh ${REMOTE_HOST} ${REMOTE_CTR} logs newscollector     # View logs"
echo "  ssh ${REMOTE_HOST} cd ~/${REMOTE_DIR} && ${COMPOSE_CMD} logs -f  # View all logs"
echo "  ssh ${REMOTE_HOST} cd ~/${REMOTE_DIR} && ${COMPOSE_CMD} down     # Stop containers"
echo "  ssh ${REMOTE_HOST} cd ~/${REMOTE_DIR} && ${COMPOSE_CMD} up -d   # Restart containers"
echo "  ./scripts/import-data.sh ${REMOTE_HOST}                    # Import data"
