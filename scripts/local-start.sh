#!/usr/bin/env bash
#
# Local deployment script for NewsCollector
# Uses podman compose, docker compose, or runs directly on host
#
# Usage: ./scripts/local-start.sh [options]
#
# Options:
#   --with-db     Include PostgreSQL database
#   --clean       Clean up existing containers/processes first
#   --rebuild     Rebuild Docker/Podman image
#   --no-container  Force direct host execution (no containers)

set -euo pipefail

# Configuration
CONTAINER_NAME="newscollector"
IMAGE_NAME="localhost/newscollector"
IMAGE_TAG="local"
COMPOSE_FILE="docker-compose.yml"
WITH_DB=""
CLEAN=""
REBUILD=""
FORCE_HOST=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Start NewsCollector service locally for testing."
    echo ""
    echo "Options:"
    echo "  --with-db       Include PostgreSQL database"
    echo "  --clean         Clean up existing containers/processes first"
    echo "  --rebuild       Rebuild Docker/Podman image"
    echo "  --no-container  Force direct host execution (no containers)"
    echo ""
    echo "Detection order:"
    echo "  1. podman compose (if podman available)"
    echo "  2. docker compose (if docker available)"
    echo "  3. Direct execution on host"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-db)
            WITH_DB="yes"
            shift
            ;;
        --clean)
            CLEAN="yes"
            shift
            ;;
        --rebuild)
            REBUILD="yes"
            shift
            ;;
        --no-container)
            FORCE_HOST="yes"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Detect available runtime
detect_runtime() {
    if [[ "$FORCE_HOST" == "yes" ]]; then
        echo "host"
        return
    fi

    if command -v podman &> /dev/null; then
        if podman compose version &> /dev/null || podman --version | grep -q "compose"; then
            echo "podman"
            return
        fi
    fi

    if command -v docker &> /dev/null; then
        echo "docker"
        return
    fi

    # Check for docker compose (standalone)
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
        return
    fi

    echo "host"
}

RUNTIME=$(detect_runtime)
log_info "Detected runtime: ${RUNTIME}"

# Create required directories
setup_directories() {
    log_info "Setting up directories..."
    mkdir -p output/sqldata output/collected output/reports output/verdicts
    mkdir -p config

    if [[ ! -f "config/config.yaml" ]]; then
        cat > config/config.yaml << 'EOF'
# NewsCollector Configuration
twitter:
  bearer_token: ""
youtube:
  api_key: ""
rednote:
  cookies: ""
ai:
  ai_base_url: ""
  ai_model: ""
  ai_api_key: ""
storage:
  database_url: ""
EOF
        log_ok "Created config/config.yaml"
    else
        log_ok "Config already exists"
    fi
}

# Clean up existing services
cleanup() {
    log_info "Cleaning up existing services..."

    case "$RUNTIME" in
        podman|docker)
            podman compose -f "$COMPOSE_FILE" down 2>/dev/null || true
            docker compose -f "$COMPOSE_FILE" down 2>/dev/null || true
            ;;
        docker-compose)
            docker-compose -f "$COMPOSE_FILE" down 2>/dev/null || true
            ;;
        host)
            # Kill existing processes
            pkill -f "uvicorn newscollector.web" 2>/dev/null || true
            pkill -f "python.*newscollector serve" 2>/dev/null || true
            # Stop postgres if running locally
            if command -v pg_ctl &> /dev/null; then
                pg_ctl -D output/sqldata stop 2>/dev/null || true
            fi
            ;;
    esac

    log_ok "Cleanup complete"
}

# Start with podman/docker compose
start_compose() {
    local container_runtime="$1"

    log_info "Starting with ${container_runtime} compose..."

    # Build image if needed
    if [[ "$REBUILD" == "yes" ]]; then
        log_info "Building image..."
        if [[ "$container_runtime" == "podman" ]]; then
            podman build --no-cache -t "${IMAGE_NAME}:${IMAGE_TAG}" .
        else
            docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
        fi
    fi

    # Create network if not exists
    if ! "${container_runtime}" network inspect shared-network &> /dev/null; then
        log_info "Creating shared network..."
        "${container_runtime}" network create shared-network
    fi

    # Start services
    if [[ "$container_runtime" == "podman" ]]; then
        if [[ "$WITH_DB" == "yes" ]]; then
            podman compose -f "$COMPOSE_FILE" up -d
        else
            podman compose -f "$COMPOSE_FILE" up -d newscollector
        fi
    else
        if [[ "$WITH_DB" == "yes" ]]; then
            docker compose -f "$COMPOSE_FILE" up -d
        else
            docker compose -f "$COMPOSE_FILE" up -d newscollector
        fi
    fi

    log_ok "Services started"
}

# Start directly on host
start_host() {
    log_info "Starting services directly on host..."

    # Install dependencies if needed
    if ! python3 -c "import fastapi" 2>/dev/null; then
        log_info "Installing Python dependencies..."
        pip3 install -q -r requirements.txt
    fi

    # Start PostgreSQL if requested
    if [[ "$WITH_DB" == "yes" ]]; then
        log_info "Starting PostgreSQL..."

        # Check if postgres is available
        if command -v pg_ctl &> /dev/null; then
            # Use existing postgres
            if [[ ! -d "output/sqldata" ]]; then
                initdb -D output/sqldata
            fi
            pg_ctl -D output/sqldata -l output/sqldata/logfile start
        elif command -v createdb &> /dev/null; then
            createdb newscollector 2>/dev/null || true
        else
            log_warn "PostgreSQL not available, using file storage instead"
        fi

        # Update config with database URL
        if command -v pg_ctl &> /dev/null; then
            sed -i 's|database_url: ""|database_url: "postgresql://$USER@localhost:5432/newscollector"|' config/config.yaml
        fi
    fi

    # Start web server
    log_info "Starting web server..."
    nohup python3 -m newscollector serve --host 0.0.0.0 --port 8000 > output/server.log 2>&1 &
    SERVER_PID=$!

    # Wait for server to start
    sleep 3

    if kill -0 "$SERVER_PID" 2>/dev/null; then
        log_ok "Web server started (PID: $SERVER_PID)"
    else
        log_error "Failed to start web server. Check output/server.log"
        cat output/server.log
        exit 1
    fi
}

# Main
setup_directories

if [[ "$CLEAN" == "yes" ]]; then
    cleanup
fi

case "$RUNTIME" in
    podman|docker|docker-compose)
        start_compose "$RUNTIME"
        ;;
    host)
        start_host
        ;;
esac

# Wait and verify
sleep 3

echo ""
echo "=========================================="
log_ok "NewsCollector is running!"
echo "=========================================="
echo ""
echo "Web UI:     http://localhost:8000"
echo "Runtime:    ${RUNTIME}"
echo "Data dir:   ${PWD}/output/"
echo ""

case "$RUNTIME" in
    podman)
        echo "Useful commands:"
        echo "  podman compose logs -f        # View logs"
        echo "  podman compose down           # Stop"
        ;;
    docker)
        echo "Useful commands:"
        echo "  docker compose logs -f        # View logs"
        echo "  docker compose down           # Stop"
        ;;
    host)
        echo "Useful commands:"
        echo "  tail -f output/server.log    # View logs"
        echo "  pkill -f 'newscollector serve'  # Stop"
        ;;
esac

echo ""
