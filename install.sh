#!/bin/bash
# install.sh — RedTeam Agent installation script
# Usage: ./install.sh              (from project root)
#    or: bash <(curl -fsSL URL)    (auto-clones then installs)
set -e

REPO_URL="https://github.com/NeoTheCapt/RedteamAgent.git"
INSTALL_DIR="${REDTEAM_DIR:-$HOME/redteam-agent}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   RedTeam Agent — Installation Script                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# If not in a project directory (no .opencode/opencode.json), clone first
if [ ! -f ".opencode/opencode.json" ]; then
    echo "Not in project directory. Cloning to $INSTALL_DIR ..."
    if [ -d "$INSTALL_DIR/.opencode" ]; then
        echo "Directory $INSTALL_DIR already exists. Updating..."
        cd "$INSTALL_DIR" && git pull origin dev 2>/dev/null || true
    else
        git clone -b dev "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
    echo "Working in: $(pwd)"
    echo ""
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "  ${BLUE}[INFO]${NC} $1"; }

ERRORS=0

# ============================================
# Step 1: Check prerequisites
# ============================================
echo "Step 1: Checking prerequisites..."
echo ""

# Docker
if command -v docker >/dev/null 2>&1; then
    DOCKER_VERSION=$(docker --version 2>&1 | head -1)
    ok "Docker: $DOCKER_VERSION"
else
    fail "Docker is not installed"
    info "Install from: https://docs.docker.com/get-docker/"
    ERRORS=$((ERRORS + 1))
fi

# Docker daemon running
if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running"
else
    fail "Docker daemon is not running"
    info "Start Docker Desktop or run: sudo systemctl start docker"
    ERRORS=$((ERRORS + 1))
fi

# Docker Compose
if docker compose version >/dev/null 2>&1; then
    COMPOSE_VERSION=$(docker compose version --short 2>&1)
    ok "Docker Compose: $COMPOSE_VERSION"
elif command -v docker-compose >/dev/null 2>&1; then
    ok "Docker Compose (standalone): $(docker-compose --version 2>&1 | head -1)"
else
    fail "Docker Compose is not available"
    info "Included with Docker Desktop, or install: https://docs.docker.com/compose/install/"
    ERRORS=$((ERRORS + 1))
fi

# OpenCode
if command -v opencode >/dev/null 2>&1; then
    OPENCODE_VERSION=$(opencode --version 2>&1 | head -1 || echo "unknown")
    ok "OpenCode: $OPENCODE_VERSION"
else
    fail "OpenCode is not installed"
    info "Install from: https://opencode.ai or npm install -g opencode-ai"
    ERRORS=$((ERRORS + 1))
fi

# curl
if command -v curl >/dev/null 2>&1; then
    ok "curl: $(curl --version 2>&1 | head -1 | awk '{print $2}')"
else
    fail "curl is not installed"
    ERRORS=$((ERRORS + 1))
fi

# jq
if command -v jq >/dev/null 2>&1; then
    ok "jq: $(jq --version 2>&1)"
else
    fail "jq is not installed"
    info "Install: brew install jq (macOS) or apt install jq (Linux)"
    ERRORS=$((ERRORS + 1))
fi

# sqlite3
if command -v sqlite3 >/dev/null 2>&1; then
    ok "sqlite3: $(sqlite3 --version 2>&1 | awk '{print $1}')"
else
    fail "sqlite3 is not installed"
    info "Install: brew install sqlite3 (macOS) or apt install sqlite3 (Linux)"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ $ERRORS -gt 0 ]; then
    fail "$ERRORS prerequisite(s) missing. Please install them and re-run."
    exit 1
fi
ok "All prerequisites satisfied"

# ============================================
# Step 2: Build Docker images
# ============================================
echo ""
echo "Step 2: Building Docker images..."
echo ""

info "This may take several minutes on first run (downloading Kali base image ~2GB)"
echo ""

# Pull Katana (official image)
info "Pulling projectdiscovery/katana:latest..."
if docker pull projectdiscovery/katana:latest >/dev/null 2>&1; then
    ok "Katana image: $(docker images projectdiscovery/katana:latest --format '{{.Size}}')"
else
    fail "Failed to pull Katana image"
    ERRORS=$((ERRORS + 1))
fi

# Build kali-redteam
info "Building kali-redteam (Kali toolbox)... this is the largest image"
if cd docker && docker compose build kali-redteam 2>&1 | tail -3; then
    cd ..
    ok "kali-redteam: $(docker images kali-redteam:latest --format '{{.Size}}')"
else
    cd ..
    fail "Failed to build kali-redteam"
    ERRORS=$((ERRORS + 1))
fi

# Build mitmproxy
info "Building redteam-proxy (mitmproxy)..."
if cd docker && docker compose build mitmproxy 2>&1 | tail -3; then
    cd ..
    ok "redteam-proxy: $(docker images redteam-proxy:latest --format '{{.Size}}')"
else
    cd ..
    fail "Failed to build redteam-proxy"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ $ERRORS -gt 0 ]; then
    fail "Some images failed to build. Check Docker logs above."
    exit 1
fi

# ============================================
# Step 3: Verify images
# ============================================
echo ""
echo "Step 3: Verifying images..."
echo ""

source scripts/lib/container.sh 2>/dev/null
if check_images; then
    ok "All 3 images verified"
else
    fail "Image verification failed"
    exit 1
fi

# ============================================
# Step 4: Test container execution
# ============================================
echo ""
echo "Step 4: Quick smoke test..."
echo ""

# Test run_tool
mkdir -p /tmp/redteam-test
export ENGAGEMENT_DIR="/tmp/redteam-test"
if run_tool echo "Container execution works" >/dev/null 2>&1; then
    ok "run_tool: container execution works"
else
    fail "run_tool: container execution failed"
    ERRORS=$((ERRORS + 1))
fi

# Test tool availability inside container
TOOL_COUNT=$(run_tool sh -c 'for t in nmap ffuf sqlmap nikto whatweb hydra gobuster nuclei wfuzz; do command -v $t >/dev/null 2>&1 && echo ok; done' 2>/dev/null | wc -l | tr -d ' ')
ok "Tools available in container: $TOOL_COUNT/9"

# Cleanup
rm -r /tmp/redteam-test 2>/dev/null

# ============================================
# Step 5: Set executable permissions
# ============================================
echo ""
echo "Step 5: Setting permissions..."
echo ""

chmod +x scripts/*.sh scripts/lib/*.sh 2>/dev/null
ok "Script permissions set"

# ============================================
# Step 6: Check OpenCode config
# ============================================
echo ""
echo "Step 6: Checking OpenCode configuration..."
echo ""

if [ -f ".opencode/opencode.json" ]; then
    MODEL=$(jq -r '.model // empty' .opencode/opencode.json)
    if [ -z "$MODEL" ]; then
        warn "No model configured in .opencode/opencode.json"
        info "Edit .opencode/opencode.json and set 'model' to your provider, e.g.:"
        info '  "model": "anthropic/claude-sonnet-4-5"'
        info '  "model": "openai/gpt-4o"'
    else
        ok "Model configured: $MODEL"
    fi
else
    fail ".opencode/opencode.json not found"
    ERRORS=$((ERRORS + 1))
fi

# ============================================
# Done
# ============================================
echo ""
echo "════════════════════════════════════════════════════════════════"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Installation completed with $ERRORS error(s). Fix issues above and re-run.${NC}"
    exit 1
else
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "  Next steps:"
    echo ""
    echo "  1. Configure your LLM model in .opencode/opencode.json:"
    echo '     "model": "anthropic/claude-sonnet-4-5"'
    echo ""
    echo "  2. Start the agent:"
    echo "     opencode"
    echo ""
    echo "  3. Begin an engagement:"
    echo "     /engage http://your-ctf-target:port"
    echo ""
fi
