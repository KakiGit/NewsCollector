#!/usr/bin/env bash
#
# Test script for local NewsCollector deployment
# Tests podman compose, docker compose, or direct host execution
#
# Usage: ./scripts/local-test.sh

set -euo pipefail

# Configuration
CONTAINER_NAME="newscollector"
COMPOSE_FILE="docker-compose.yml"

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

TESTS_PASSED=0
TESTS_FAILED=0

test_result() {
    if [[ $1 -eq 0 ]]; then
        log_ok "$2"
        ((TESTS_PASSED++))
    else
        log_error "$2"
        ((TESTS_FAILED++))
    fi
}

# Detect runtime
detect_runtime() {
    if podman ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        echo "podman"
        return
    fi
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        echo "docker"
        return
    fi
    # Check for direct host process
    if pgrep -f "uvicorn newscollector.web" > /dev/null || pgrep -f "python.*newscollector serve" > /dev/null; then
        echo "host"
        return
    fi
    echo "none"
}

RUNTIME=$(detect_runtime)

echo "=========================================="
echo "  NewsCollector Local Test Suite"
echo "=========================================="
echo ""
log_info "Detected runtime: ${RUNTIME}"

# Test 1: Service is running
log_info "Test 1: Service is running..."
case "$RUNTIME" in
    podman|docker)
        if "${RUNTIME}" ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
            test_result 0 "Container is running"
        else
            test_result 1 "Container is NOT running"
        fi
        ;;
    host)
        if pgrep -f "uvicorn" > /dev/null || pgrep -f "newscollector serve" > /dev/null; then
            test_result 0 "Web server process is running"
        else
            test_result 1 "Web server is NOT running"
        fi
        ;;
    *)
        test_result 1 "No service detected"
        ;;
esac

# Test 2: Container/process is stable
log_info "Test 2: Service is stable..."
case "$RUNTIME" in
    podman|docker)
        STATUS=$("${RUNTIME}" ps --filter "name=${CONTAINER_NAME}" --format '{{.Status}}' 2>/dev/null || echo "")
        if echo "$STATUS" | grep -q "Up"; then
            if echo "$STATUS" | grep -q "Restarting"; then
                test_result 1 "Service is restarting"
            else
                test_result 0 "Service is stable"
            fi
        else
            test_result 1 "Service is not running"
        fi
        ;;
    host)
        # Check if process is not restarting
        if pgrep -f "newscollector serve" > /dev/null; then
            test_result 0 "Service is stable"
        else
            test_result 1 "Service is not running"
        fi
        ;;
    *)
        test_result 1 "Cannot check stability"
        ;;
esac

# Test 3: Web UI is accessible
log_info "Test 3: Web UI is accessible..."
if curl -sf http://localhost:8000/health &>/dev/null; then
    test_result 0 "Web UI is responding (health endpoint)"
elif curl -sf http://localhost:8000/ &>/dev/null; then
    test_result 0 "Web UI is responding"
else
    test_result 1 "Web UI is NOT accessible"
fi

# Test 4: Data directory exists and is writable
log_info "Test 4: Data directory is accessible..."
if [[ -d "output" ]]; then
    if touch "output/.test-write" 2>/dev/null; then
        rm "output/.test-write"
        test_result 0 "Output directory is writable"
    else
        test_result 1 "Output directory is NOT writable"
    fi
else
    test_result 1 "Output directory does NOT exist"
fi

# Test 5: Config file exists
log_info "Test 5: Config file exists..."
if [[ -f "config/config.yaml" ]]; then
    test_result 0 "Config file exists"
else
    test_result 1 "Config file does NOT exist"
fi

# Test 6: Check logs for errors
log_info "Test 6: Checking for critical errors..."
case "$RUNTIME" in
    podman|docker)
        LOGS=$("${RUNTIME}" logs "${CONTAINER_NAME}" 2>&1 | tail -50)
        ;;
    host)
        LOGS=$(tail -50 output/server.log 2>/dev/null || echo "")
        ;;
    *)
        LOGS=""
        ;;
esac

ERRORS=$(echo "$LOGS" | grep -iE "(error|exception|fatal)" | grep -v "ERROR.*404" | grep -v "ERROR.*Connection" | grep -v "uvicorn.error" | tail -5 || true)
if [[ -n "$ERRORS" ]]; then
    log_warn "Found potential errors:"
    echo "$ERRORS" | head -3 | sed 's/^/  /'
    ((TESTS_FAILED++))
else
    test_result 0 "No critical errors in logs"
fi

# Test 7: Network/port check
log_info "Test 7: Port 8000 is listening..."
if command -v ss &> /dev/null; then
    if ss -tlnp | grep -q ":8000"; then
        test_result 0 "Port 8000 is listening"
    else
        test_result 1 "Port 8000 is NOT listening"
    fi
elif command -v netstat &> /dev/null; then
    if netstat -tln | grep -q ":8000"; then
        test_result 0 "Port 8000 is listening"
    else
        test_result 1 "Port 8000 is NOT listening"
    fi
else
    # Fallback: try curl again
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        test_result 0 "Port 8000 is responding"
    else
        test_result 1 "Cannot verify port"
    fi
fi

# Summary
echo ""
echo "=========================================="
echo "  Test Results"
echo "=========================================="
echo ""
echo -e "Passed: ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Failed: ${RED}${TESTS_FAILED}${NC}"
echo ""

if [[ $TESTS_FAILED -eq 0 ]]; then
    log_ok "All tests passed!"
    exit 0
else
    log_error "Some tests failed!"
    echo ""
    echo "Debug commands:"
    case "$RUNTIME" in
        podman)
            echo "  podman compose logs -f      # View logs"
            echo "  podman ps                   # List containers"
            ;;
        docker)
            echo "  docker compose logs -f      # View logs"
            echo "  docker ps                   # List containers"
            ;;
        host)
            echo "  tail -f output/server.log   # View logs"
            echo "  pgrep -a newscollector     # List processes"
            ;;
    esac
    echo "  curl http://localhost:8000/   # Test web UI"
    exit 1
fi
