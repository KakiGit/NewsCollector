#!/usr/bin/env bash
#
# Import data to NewsCollector on remote server via SSH
#
# Usage: ./scripts/import-data.sh <hostname> [local-path]
#
# If local-path is not provided, imports from ./output directory
#
# Supported data types:
#   - JSON files in output/collected/ format
#   - Financial reports in output/reports/ format

set -euo pipefail

# Configuration
REMOTE_DIR="vol_news_collector"
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
    echo "Usage: $0 <remote-host> [local-path]"
    echo ""
    echo "Import data to NewsCollector on a remote server via SSH."
    echo ""
    echo "Arguments:"
    echo "  remote-host    SSH hostname or user@hostname"
    echo "  local-path     Optional: local data path (default: ./output)"
    echo ""
    echo "Examples:"
    echo "  $0 myserver                           # Import from ./output"
    echo "  $0 myserver ./my-data                 # Import from custom path"
    echo "  $0 myserver ./output/collected/      # Import collected items"
    echo "  $0 myserver ./output/reports/         # Import financial reports"
    exit 1
}

# Check arguments
if [[ $# -lt 1 ]]; then
    log_error "Missing required argument: remote host"
    usage
fi

REMOTE_HOST="$1"
LOCAL_PATH="${2:-./output}"

# Verify SSH connectivity
log_info "Verifying SSH connectivity to ${REMOTE_HOST}..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_HOST" "exit 0" 2>/dev/null; then
    log_error "Cannot connect to ${REMOTE_HOST} via SSH"
    exit 1
fi
log_ok "SSH connection verified"

# Detect container runtime
if ssh "$REMOTE_HOST" "command -v podman" &> /dev/null; then
    REMOTE_CTR="podman"
elif ssh "$REMOTE_HOST" "command -v docker" &> /dev/null; then
    REMOTE_CTR="docker"
else
    log_error "Neither Docker nor Podman found on remote host"
    exit 1
fi

# Check if container is running
log_info "Checking container status..."
if ! ssh "$REMOTE_HOST" "${REMOTE_CTR} ps --filter name=${CONTAINER_NAME} --format '{{.Status}}'" | grep -q "Up"; then
    log_error "Container is not running. Start it first with:"
    echo "  ./scripts/start.sh ${REMOTE_HOST}"
    exit 1
fi
log_ok "Container is running"

# Verify local path exists
if [[ ! -e "$LOCAL_PATH" ]]; then
    log_error "Local path does not exist: ${LOCAL_PATH}"
    exit 1
fi

# Determine what to import based on directory structure
log_info "Analyzing data to import..."

# Create temp directory for transfer
TMP_DIR=$(mktemp -d)
TAR_FILE="${TMP_DIR}/import-data.tar.gz"
trap "rm -rf $TMP_DIR" EXIT

# Package the data
log_info "Packaging data from ${LOCAL_PATH}..."
tar -czf "$TAR_FILE" -C "$(dirname "$LOCAL_PATH")" "$(basename "$LOCAL_PATH")"
log_ok "Data packaged ($(du -h "$TAR_FILE" | cut -f1))"

# Transfer to remote
log_info "Transferring data to ${REMOTE_HOST}..."
scp "$TAR_FILE" "${REMOTE_HOST}:~/${REMOTE_DIR}/data/import.tar.gz"

# Extract on remote
log_info "Extracting data on remote..."
ssh "$REMOTE_HOST" "cd ~/${REMOTE_DIR}/output && tar -xzf ../data/import.tar.gz"

# Determine data type and show import info
if [[ -d "$LOCAL_PATH/collected" ]]; then
    COUNT=$(find "$LOCAL_PATH/collected" -name "*.json" 2>/dev/null | wc -l)
    log_ok "Found ${COUNT} collected data files"
    log_info "Data imported to: ~/${REMOTE_DIR}/output/collected/"
elif [[ -d "$LOCAL_PATH/reports" ]]; then
    COUNT=$(find "$LOCAL_PATH/reports" -name "*.json" 2>/dev/null | wc -l)
    log_ok "Found ${COUNT} financial report files"
    log_info "Data imported to: ~/${REMOTE_DIR}/output/reports/"
elif [[ -d "$LOCAL_PATH/verdicts" ]]; then
    COUNT=$(find "$LOCAL_PATH/verdicts" -name "*.json" 2>/dev/null | wc -l)
    log_ok "Found ${COUNT} verdict files"
    log_info "Data imported to: ~/${REMOTE_DIR}/output/verdicts/"
else
    # Generic import - list what was imported
    log_ok "Data imported to: ~/${REMOTE_DIR}/output/"
    ssh "$REMOTE_HOST" "ls -la ~/${REMOTE_DIR}/output/"
fi

# Clean up remote temp file
log_info "Cleaning up..."
ssh "$REMOTE_HOST" "rm -f ~/${REMOTE_DIR}/data/import.tar.gz"

log_ok "Import complete!"
echo ""
echo "You can view the data in the web UI: http://${REMOTE_HOST}:8000"
