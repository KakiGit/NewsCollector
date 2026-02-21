#!/usr/bin/env bash
#
# Deploy NewsCollector container to a remote machine via SSH
#
# Usage: ./scripts/deploy.sh <hostname>
#
# Prerequisites:
#   - SSH access to the remote host (preferably with key-based auth)
#   - Docker or Podman installed on the remote machine

set -euo pipefail

# Configuration
IMAGE_NAME="localhost/newscollector"
IMAGE_TAG="latest"
CONTAINER_NAME="newscollector"
REMOTE_DIR="vol_news_collector"
TMP_FILE="/tmp/news-collector-${IMAGE_TAG}.tar.gz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    echo "Usage: $0 <remote-host>"
    echo ""
    echo "Deploy NewsCollector container to a remote machine."
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

cleanup() {
    if [[ -f "$TMP_FILE" ]]; then
        log_info "Cleaning up local temp file..."
        rm -f "$TMP_FILE"
    fi
}

trap cleanup EXIT

# Check arguments
if [[ $# -lt 1 ]]; then
    log_error "Missing required argument: remote host"
    usage
fi

REMOTE_HOST="$1"

# Verify required commands exist
for cmd in docker ssh scp gzip; do
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

# Check if remote needs initial setup
log_info "Checking if remote needs initial setup..."
if ! ssh "$REMOTE_HOST" "test -d ~/${REMOTE_DIR}" 2>/dev/null; then
    log_warn "Remote directory not found. Running setup first..."
    ./scripts/setup.sh "$REMOTE_HOST"
fi

# Build the image locally
log_info "Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
log_ok "Image built successfully"

# Save and compress the image
log_info "Saving and compressing image to ${TMP_FILE}..."
docker save "${IMAGE_NAME}:${IMAGE_TAG}" | gzip > "$TMP_FILE"
log_ok "Image saved ($(du -h "$TMP_FILE" | cut -f1))"

# Transfer the image
log_info "Transferring image to ${REMOTE_HOST}..."
scp "$TMP_FILE" "${REMOTE_HOST}:~/${REMOTE_DIR}/"
log_ok "Transfer complete"

# Stop existing container (if running)
log_info "Stopping existing container (if any)..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} stop ${CONTAINER_NAME} 2>/dev/null || true"
ssh "$REMOTE_HOST" "${REMOTE_CTR} rm ${CONTAINER_NAME} 2>/dev/null || true"
log_ok "Old container stopped"

# Load the new image
log_info "Loading image on remote host..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} load -i ~/${REMOTE_DIR}/$(basename "$TMP_FILE")"
log_ok "Image loaded"

# Clean up remote tar file
log_info "Cleaning up remote temp file..."
ssh "$REMOTE_HOST" "rm -f ~/${REMOTE_DIR}/$(basename "$TMP_FILE")"

# Remove dangling images to save space
log_info "Removing old dangling images..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} image prune -f" > /dev/null 2>&1 || true

# Start the new container
log_info "Starting new container..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} run -d \
    --name ${CONTAINER_NAME} \
    --restart unless-stopped \
    -p 8000:8000 \
    -v ~/${REMOTE_DIR}/config/config.yaml:/app/config/config.yaml:ro \
    -v ~/${REMOTE_DIR}/output:/app/output \
    ${IMAGE_NAME}:${IMAGE_TAG}"

log_ok "Container started successfully"

# Verify container is running
log_info "Verifying container status..."
if ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=${CONTAINER_NAME} --format '{{.Status}}'" | grep -q "Up"; then
    log_ok "Deployment complete! Container is running on ${REMOTE_HOST}"
    echo ""
    echo "Container details:"
    ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=${CONTAINER_NAME} --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
else
    log_error "Container may have failed to start. Check logs with:"
    echo "  ssh ${REMOTE_HOST} ${REMOTE_CTR} logs ${CONTAINER_NAME}"
    exit 1
fi

echo ""
log_ok "Deployment successful!"
echo ""
echo "To access the web UI, open: http://${REMOTE_HOST}:8000"
echo ""
echo "Useful commands:"
echo "  ssh ${REMOTE_HOST} ${REMOTE_CTR} logs ${CONTAINER_NAME}  # View logs"
echo "  ssh ${REMOTE_HOST} ${REMOTE_CTR} stop ${CONTAINER_NAME}  # Stop container"
echo "  ./scripts/import-data.sh ${REMOTE_HOST}                  # Import data"
