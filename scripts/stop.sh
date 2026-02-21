#!/usr/bin/env bash
#
# Stop the NewsCollector service on remote server
#
# Usage: ./scripts/stop.sh <hostname>
#
# Stops the container gracefully

set -euo pipefail

# Configuration
CONTAINER_NAME="newscollector"

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
    echo "Stop the NewsCollector service on a remote server."
    echo ""
    echo "Arguments:"
    echo "  remote-host    SSH hostname or user@hostname"
    echo ""
    echo "Examples:"
    echo "  $0 myserver"
    echo "  $0 user@192.168.1.100"
    exit 1
}

# Check arguments
if [[ $# -lt 1 ]]; then
    log_error "Missing required argument: remote host"
    usage
fi

REMOTE_HOST="$1"

# Verify SSH connectivity
log_info "Verifying SSH connectivity to ${REMOTE_HOST}..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_HOST" "exit 0" 2>/dev/null; then
    log_error "Cannot connect to ${REMOTE_HOST} via SSH"
    exit 1
fi

# Detect container runtime
if ssh "$REMOTE_HOST" "command -v podman" &> /dev/null; then
    REMOTE_CTR="podman"
elif ssh "$REMOTE_HOST" "command -v docker" &> /dev/null; then
    REMOTE_CTR="docker"
else
    log_error "Neither Docker nor Podman found on remote host"
    exit 1
fi

# Check if container exists
log_info "Checking container status..."
if ! ssh "$REMOTE_HOST" "${REMOTE_CTR} ps -a --filter name=${CONTAINER_NAME} --format '{{.Names}}'" | grep -q "^${CONTAINER_NAME}$"; then
    log_warn "Container not found. Nothing to stop."
    exit 0
fi

# Check if container is running
if ! ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=${CONTAINER_NAME} --format '{{.Status}}'" | grep -q "Up"; then
    log_warn "Container is not running"
    exit 0
fi

# Stop the container
log_info "Stopping container..."
ssh "$REMOTE_HOST" "${REMOTE_CTR} stop ${CONTAINER_NAME}"
log_ok "Container stopped"

# Show container status
echo ""
ssh "$REMOTE_HOST" "${REMOTE_CTR} ps -a --filter name=${CONTAINER_NAME} --format 'table {{.Names}}\t{{.Status}}'"
