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

if [ -n "${REDTEAM_OPENCODE_MODEL:-}" ] || [ -n "${REDTEAM_OPENCODE_SMALL_MODEL:-}" ]; then
  python3 - "$WORKSPACE_DIR/.opencode/opencode.json" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.exists():
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = os.environ.get("REDTEAM_OPENCODE_MODEL", "").strip()
    small_model = os.environ.get("REDTEAM_OPENCODE_SMALL_MODEL", "").strip()
    if model:
        payload["model"] = model
    if small_model:
        payload["small_model"] = small_model
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
fi

export REDTEAM_RUNTIME_MODE="${REDTEAM_RUNTIME_MODE:-local}"
export KATANA_LOCAL_BIN="${KATANA_LOCAL_BIN:-/usr/local/bin/katana}"
export KATANA_CHROME_BIN="${KATANA_CHROME_BIN:-/usr/bin/chromium}"
export KATANA_HEADLESS_OPTIONS="${KATANA_HEADLESS_OPTIONS:---no-sandbox,--disable-dev-shm-usage,--disable-gpu}"
export MSF_SERVER="${MSF_SERVER:-127.0.0.1}"
export MSF_PORT="${MSF_PORT:-55553}"

exec "$@"
