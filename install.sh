#!/bin/bash
# install.sh — RedTeam Agent installation script
#
# Usage:
#   ./install.sh opencode [target_dir]           Install for OpenCode
#   ./install.sh claude [target_dir]             Install for Claude Code
#   ./install.sh codex [target_dir]              Install for Codex
#   ./install.sh --dry-run opencode              Validate without writing
#   bash <(curl -fsSL URL) opencode ~/my-agent   Auto-clone and install
#
# Supported platforms: macOS and Linux only.
# Windows is intentionally unsupported because the runtime depends on Unix-first
# tooling and Docker workflows that are not maintained for native PowerShell.
#
# target_dir defaults to ~/redteam-agent if not specified.
# Each product gets ONLY its own files — no cross-product contamination.
set -e

# ============================================
# Parse arguments
# ============================================
DRY_RUN=false
PRODUCT=""
TARGET_DIR=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    opencode|claude|codex) PRODUCT="$arg" ;;
    *) [ -z "$TARGET_DIR" ] && TARGET_DIR="$arg" ;;
  esac
done

if [ -z "$PRODUCT" ]; then
  echo "Usage: $0 [--dry-run] <opencode|claude|codex> [target_dir]"
  echo ""
  echo "  opencode  — Install for OpenCode (source files, no build needed)"
  echo "  claude    — Install for Claude Code (generates .claude/agents + commands)"
  echo "  codex     — Install for Codex (generates .codex/agents)"
  echo ""
  echo "  Supported platforms: macOS, Linux"
  echo "  Windows / PowerShell: not supported"
  echo ""
  echo "  target_dir defaults to ~/redteam-agent"
  exit 1
fi

REPO_URL="https://github.com/NeoTheCapt/RedteamAgent.git"
INSTALL_DIR="${TARGET_DIR:-${REDTEAM_DIR:-$HOME/redteam-agent}}"

echo ""
if $DRY_RUN; then
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   RedTeam Agent — DRY RUN ($PRODUCT)                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
else
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   RedTeam Agent — Install for $PRODUCT                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
fi
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "  ${BLUE}[INFO]${NC} $1"; }

ERRORS=0

# Determine source directory
SOURCE_DIR=""
if [ -d "agent/.opencode" ]; then
    SOURCE_DIR="$(pwd)/agent"
    info "Found agent/ in current directory"
elif [ -f ".opencode/opencode.json" ] && [ -d "skills" ]; then
    SOURCE_DIR="$(pwd)"
    info "Running from agent directory"
else
    echo "Not in project directory. Cloning to /tmp/redteam-agent-src ..."
    CLONE_DIR="/tmp/redteam-agent-src"
    rm -rf "$CLONE_DIR"
    git clone -b dev "$REPO_URL" "$CLONE_DIR"
    SOURCE_DIR="$CLONE_DIR/agent"
    echo "Working from: $SOURCE_DIR"
    echo ""
fi

OPENCODE_JSON="$SOURCE_DIR/.opencode/opencode.json"
TXT_DIR="$SOURCE_DIR/.opencode/prompts/agents"

# ============================================
# Step 1: Check prerequisites
# ============================================
echo "Step 1: Checking prerequisites..."
echo ""

# Docker
if command -v docker >/dev/null 2>&1; then
    ok "Docker: $(docker --version 2>&1 | head -1)"
else
    fail "Docker is not installed"
    ERRORS=$((ERRORS + 1))
fi

if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running"
else
    fail "Docker daemon is not running"
    ERRORS=$((ERRORS + 1))
fi

# Product-specific CLI check
case "$PRODUCT" in
  opencode)
    if command -v opencode >/dev/null 2>&1; then
        ok "OpenCode: $(opencode --version 2>&1 | head -1)"
    else
        fail "OpenCode not installed (npm install -g opencode-ai)"
        ERRORS=$((ERRORS + 1))
    fi ;;
  claude)
    if command -v claude >/dev/null 2>&1; then
        ok "Claude Code: $(claude --version 2>&1 | head -1)"
    else
        fail "Claude Code not installed"
        ERRORS=$((ERRORS + 1))
    fi ;;
  codex)
    if command -v codex >/dev/null 2>&1; then
        ok "Codex: $(codex --version 2>&1 | head -1)"
    else
        fail "Codex not installed"
        ERRORS=$((ERRORS + 1))
    fi ;;
esac

# Common tools
for tool in curl jq sqlite3; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool"
  else
    fail "$tool not installed"
    ERRORS=$((ERRORS + 1))
  fi
done

echo ""
if [ $ERRORS -gt 0 ]; then
    fail "$ERRORS prerequisite(s) missing."
    exit 1
fi
ok "All prerequisites satisfied"

# ============================================
# Step 2: Install product-specific files
# ============================================
echo ""
echo "Step 2: Installing for $PRODUCT to $INSTALL_DIR ..."
echo ""

# --- Helper: build Claude Code agent from .txt source ---
build_claude_agent() {
  local agent="$1" out_dir="$2"
  local txt_file="$TXT_DIR/${agent}.txt"
  [ -f "$txt_file" ] || { echo "  WARN: $txt_file not found" >&2; return; }

  local desc tools="" content
  desc=$(jq -r ".agent[\"$agent\"].description" "$OPENCODE_JSON")
  for perm in read write edit bash glob grep; do
    val=$(jq -r ".agent[\"$agent\"].$perm // false" "$OPENCODE_JSON")
    if [ "$val" = "true" ]; then
      case $perm in
        read) tools="${tools:+$tools, }Read" ;; write) tools="${tools:+$tools, }Write" ;;
        edit) tools="${tools:+$tools, }Edit" ;; bash) tools="${tools:+$tools, }Bash" ;;
        glob) tools="${tools:+$tools, }Glob" ;; grep) tools="${tools:+$tools, }Grep" ;;
      esac
    fi
  done
  content=$(cat "$txt_file")

  mkdir -p "$out_dir"
  cat > "$out_dir/${agent}.md" << MDEOF
---
name: ${agent}
description: ${desc}
tools: ${tools}
---

${content}
MDEOF
  echo "  Built: $agent (.md)"
}

# --- Helper: build Codex agent from .txt source ---
build_codex_agent() {
  local agent="$1" out_dir="$2"
  local txt_file="$TXT_DIR/${agent}.txt"
  [ -f "$txt_file" ] || { echo "  WARN: $txt_file not found" >&2; return; }

  local desc content
  desc=$(jq -r ".agent[\"$agent\"].description" "$OPENCODE_JSON")
  content=$(cat "$txt_file")

  mkdir -p "$out_dir"
  {
    echo "name = \"${agent}\""
    echo "description = \"${desc}\""
    echo ""
    echo "developer_instructions = \"\"\""
    echo "$content"
    echo "\"\"\""
  } > "$out_dir/${agent}.toml"
  echo "  Built: $agent (.toml)"
}

if $DRY_RUN; then
    info "[DRY RUN] Would install to $INSTALL_DIR"
    # Validate sources
    for agent in $(jq -r '.agent | to_entries[] | select(.value.mode == "subagent") | .key' "$OPENCODE_JSON"); do
      [ -f "$TXT_DIR/${agent}.txt" ] && ok "$agent.txt" || fail "$agent.txt missing"
    done
else
    mkdir -p "$INSTALL_DIR"

    # --- Detect upgrade: clean old installation, preserve engagements ---
    if [ -d "$INSTALL_DIR/skills" ] || [ -d "$INSTALL_DIR/.opencode" ] || [ -d "$INSTALL_DIR/.claude" ] || [ -d "$INSTALL_DIR/.codex" ]; then
        warn "Existing installation detected in $INSTALL_DIR — upgrading"
        # Preserve engagement data and .env (user config)
        for keep in engagements .env auth.json; do
            [ -e "$INSTALL_DIR/$keep" ] && mv "$INSTALL_DIR/$keep" "/tmp/redteam-preserve-$keep" 2>/dev/null
        done
        # Remove old files
        rm -rf "$INSTALL_DIR/.opencode" "$INSTALL_DIR/.claude" "$INSTALL_DIR/.codex" \
               "$INSTALL_DIR/skills" "$INSTALL_DIR/references" "$INSTALL_DIR/scripts" \
               "$INSTALL_DIR/docker" "$INSTALL_DIR/CLAUDE.md" "$INSTALL_DIR/AGENTS.md" \
               "$INSTALL_DIR/.env.example"
        # Restore preserved data
        for keep in engagements .env auth.json; do
            [ -e "/tmp/redteam-preserve-$keep" ] && mv "/tmp/redteam-preserve-$keep" "$INSTALL_DIR/$keep" 2>/dev/null
        done
        ok "Old installation cleaned (engagements + .env preserved)"
    fi

    # --- Shared files (all products need these) ---
    info "Copying shared files..."
    for dir in skills references scripts docker; do
      [ -d "$SOURCE_DIR/$dir" ] && cp -a "$SOURCE_DIR/$dir" "$INSTALL_DIR/"
    done
    mkdir -p "$INSTALL_DIR/engagements"
    # Copy .env.example if exists
    [ -f "$SOURCE_DIR/.env.example" ] && cp "$SOURCE_DIR/.env.example" "$INSTALL_DIR/"
    ok "Shared files (skills, references, scripts, docker)"

    # --- Product-specific files ---
    case "$PRODUCT" in
      opencode)
        info "Installing OpenCode files..."
        cp -a "$SOURCE_DIR/.opencode" "$INSTALL_DIR/"
        ok "OpenCode config (.opencode/)"
        # NO .claude/, NO .codex/, NO CLAUDE.md, NO AGENTS.md
        ;;

      claude)
        info "Building and installing Claude Code files..."
        # Generate agents
        mkdir -p "$INSTALL_DIR/.claude/agents"
        for agent in $(jq -r '.agent | to_entries[] | select(.value.mode == "subagent") | .key' "$OPENCODE_JSON"); do
          build_claude_agent "$agent" "$INSTALL_DIR/.claude/agents"
        done
        # Copy commands
        mkdir -p "$INSTALL_DIR/.claude/commands"
        cp "$SOURCE_DIR/.opencode/commands/"*.md "$INSTALL_DIR/.claude/commands/"
        ok "Commands ($(ls "$INSTALL_DIR/.claude/commands/"*.md | wc -l | tr -d ' ') files)"
        # Copy settings.json (hooks)
        [ -f "$SOURCE_DIR/.claude/settings.json" ] && cp "$SOURCE_DIR/.claude/settings.json" "$INSTALL_DIR/.claude/"
        ok "settings.json (hooks)"
        # Operator prompt
        cp "$SOURCE_DIR/CLAUDE.md" "$INSTALL_DIR/"
        ok "CLAUDE.md (operator prompt)"
        # NO .opencode/, NO .codex/, NO AGENTS.md
        ;;

      codex)
        info "Building and installing Codex files..."
        # Generate agents
        mkdir -p "$INSTALL_DIR/.codex/agents"
        for agent in $(jq -r '.agent | to_entries[] | select(.value.mode == "subagent") | .key' "$OPENCODE_JSON"); do
          build_codex_agent "$agent" "$INSTALL_DIR/.codex/agents"
        done
        ok "Agents ($(ls "$INSTALL_DIR/.codex/agents/"*.toml | wc -l | tr -d ' ') files)"
        # Operator prompt
        cp "$SOURCE_DIR/AGENTS.md" "$INSTALL_DIR/"
        ok "AGENTS.md (operator prompt)"
        # NO .opencode/, NO .claude/, NO CLAUDE.md
        ;;
    esac

    # Set permissions
    chmod +x "$INSTALL_DIR/scripts/"*.sh "$INSTALL_DIR/scripts/lib/"*.sh "$INSTALL_DIR/scripts/hooks/"*.sh 2>/dev/null
    ok "Script permissions set"
fi

# ============================================
# Step 3: Build Docker images
# ============================================
echo ""
echo "Step 3: Building Docker images..."
echo ""

$DRY_RUN || cd "$INSTALL_DIR"

if $DRY_RUN; then
    info "[DRY RUN] Would build Docker images if missing — skipping"
else
    # Only build/pull images that don't already exist
    if docker image inspect projectdiscovery/katana:latest >/dev/null 2>&1; then
        ok "Katana image (already exists)"
    else
        info "Pulling projectdiscovery/katana:latest..."
        if docker pull projectdiscovery/katana:latest >/dev/null 2>&1; then
            ok "Katana image"
        else
            fail "Failed to pull Katana"; ERRORS=$((ERRORS + 1))
        fi
    fi

    if docker image inspect kali-redteam:latest >/dev/null 2>&1; then
        ok "kali-redteam (already exists)"
    else
        info "Building kali-redteam (this may take several minutes)..."
        if cd docker && docker compose build kali-redteam 2>&1 | tail -3; then
            cd ..; ok "kali-redteam"
        else
            cd ..; fail "Failed to build kali-redteam"; ERRORS=$((ERRORS + 1))
        fi
    fi

    if docker image inspect redteam-proxy:latest >/dev/null 2>&1; then
        ok "redteam-proxy (already exists)"
    else
        info "Building redteam-proxy..."
        if cd docker && docker compose build mitmproxy 2>&1 | tail -3; then
            cd ..; ok "redteam-proxy"
        else
            cd ..; fail "Failed to build redteam-proxy"; ERRORS=$((ERRORS + 1))
        fi
    fi
fi

echo ""
if [ $ERRORS -gt 0 ]; then
    fail "Some images failed to build."
    exit 1
fi

# ============================================
# Step 4: Verify & smoke test
# ============================================
if $DRY_RUN; then
    echo "Step 4: [DRY RUN] Skipping verification"
else
    echo "Step 4: Verification..."
    echo ""

    source scripts/lib/container.sh 2>/dev/null
    if check_images; then
        ok "All 3 images verified"
    else
        fail "Image verification failed"
        exit 1
    fi

    mkdir -p /tmp/redteam-test
    export ENGAGEMENT_DIR="/tmp/redteam-test"
    if run_tool echo "ok" >/dev/null 2>&1; then
        ok "run_tool: container execution works"
    else
        fail "run_tool failed"; ERRORS=$((ERRORS + 1))
    fi
    rm -rf /tmp/redteam-test
fi

# ============================================
# Done
# ============================================
echo ""
echo "════════════════════════════════════════════════════════════════"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Installation completed with $ERRORS error(s).${NC}"
    exit 1
fi

echo -e "${GREEN}Installation complete! (${PRODUCT})${NC}"
echo ""
echo "  Installed to: $INSTALL_DIR"
echo "  Product: $PRODUCT"
echo ""

case "$PRODUCT" in
  opencode)
    echo "  Start:"
    echo "    cd $INSTALL_DIR && opencode"
    echo "    /engage http://your-ctf-target:port"
    ;;
  claude)
    echo "  Start:"
    echo "    cd $INSTALL_DIR && claude"
    echo "    /engage http://your-ctf-target:port"
    ;;
  codex)
    echo "  Start:"
    echo "    cd $INSTALL_DIR && codex"
    echo "    engage http://your-ctf-target:port"
    ;;
esac
echo ""

# Show installed file summary
echo "  Files installed:"
case "$PRODUCT" in
  opencode) echo "    .opencode/  skills/  references/  scripts/  docker/" ;;
  claude)   echo "    .claude/    skills/  references/  scripts/  docker/  CLAUDE.md" ;;
  codex)    echo "    .codex/     skills/  references/  scripts/  docker/  AGENTS.md" ;;
esac
echo ""
