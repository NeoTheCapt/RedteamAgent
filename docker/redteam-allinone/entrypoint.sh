#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="/opt/redteam-agent"
WORKSPACE_DIR="${REDTEAM_WORKSPACE_DIR:-/workspace}"

mkdir -p "$WORKSPACE_DIR"

if [ ! -e "$WORKSPACE_DIR/.opencode" ]; then
  cp -a "$TEMPLATE_DIR/." "$WORKSPACE_DIR/"
fi

cd "$WORKSPACE_DIR"

if [ ! -f "$WORKSPACE_DIR/.env" ] && [ -f "$WORKSPACE_DIR/.env.example" ]; then
  cp "$WORKSPACE_DIR/.env.example" "$WORKSPACE_DIR/.env"
fi

export REDTEAM_RUNTIME_MODE="${REDTEAM_RUNTIME_MODE:-local}"
export KATANA_LOCAL_BIN="${KATANA_LOCAL_BIN:-/usr/local/bin/katana}"
export KATANA_CHROME_BIN="${KATANA_CHROME_BIN:-/usr/bin/chromium}"
export KATANA_HEADLESS_OPTIONS="${KATANA_HEADLESS_OPTIONS:---no-sandbox,--disable-dev-shm-usage,--disable-gpu}"
export MSF_SERVER="${MSF_SERVER:-127.0.0.1}"
export MSF_PORT="${MSF_PORT:-55553}"

exec "$@"
