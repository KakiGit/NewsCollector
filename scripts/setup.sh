#!/usr/bin/env bash
#
# Initial setup script for remote server
# Creates directory structure and prepares environment for NewsCollector
#
# Usage: ./scripts/setup.sh <hostname>
#
# This script:
#   - Creates the remote data directory structure
#   - Creates a sample config file if none exists
#   - Creates the Docker network if needed

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
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    echo "Usage: $0 <remote-host>"
    echo ""
    echo "Perform initial setup on remote server for NewsCollector."
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

# Verify required commands exist
for cmd in ssh; do
    if ! command -v "$cmd" &> /dev/null; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done

# Verify SSH connectivity
log_info "Verifying SSH connectivity to ${REMOTE_HOST}..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_HOST" "exit 0" 2>/dev/null; then
    log_error "Cannot connect to ${REMOTE_HOST} via SSH"
    exit 1
fi
log_ok "SSH connection verified"

# Detect container runtime
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

# Create remote directory structure
log_info "Creating remote directory structure..."
ssh "$REMOTE_HOST" "mkdir -p ~/${REMOTE_DIR}/{config,output,data}"
log_ok "Directories created"

# Create sample config if not exists
log_info "Checking for config file..."
if ! ssh "$REMOTE_HOST" "test -f ~/${REMOTE_DIR}/config/config.yaml"; then
    log_info "Creating sample config file..."
    ssh "$REMOTE_HOST" "cat > ~/${REMOTE_DIR}/config/config.yaml << 'EOF'
# NewsCollector Configuration
# Edit this file to add your API keys

# X/Twitter API
twitter:
  bearer_token: ""

# YouTube Data API v3
youtube:
  api_key: ""

# RedNote (Xiaohongshu) cookies
rednote:
  cookies: ""

# AI summarization (optional)
ai:
  ai_base_url: ""
  ai_model: ""
  ai_api_key: ""

# Storage (leave empty for file-based storage)
storage:
  database_url: ""
EOF"
    log_ok "Sample config created at ~/${REMOTE_DIR}/config/config.yaml"
    log_warn "Please edit the config file to add your API keys"
else
    log_ok "Config file already exists"
fi

# Create output subdirectories
log_info "Creating output subdirectories..."
ssh "$REMOTE_HOST" "mkdir -p ~/${REMOTE_DIR}/output/{collected,reports,verdicts}"
log_ok "Output directories created"

log_info "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config: ssh ${REMOTE_HOST} 'nano ~/${REMOTE_DIR}/config/config.yaml'"
echo "  2. Deploy: ./scripts/deploy.sh ${REMOTE_HOST}"
