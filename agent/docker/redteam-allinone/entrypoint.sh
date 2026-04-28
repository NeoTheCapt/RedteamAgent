#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="/opt/redteam-agent"
WORKSPACE_DIR="${REDTEAM_WORKSPACE_DIR:-/workspace}"

mkdir -p "$WORKSPACE_DIR"

# Always re-sync the read-only template artifacts (scripts, skills,
# references, .opencode, docker) from the image into the workspace.
# Preserves user state: engagements/, .env, .env.example, auth.json,
# pids/, scans/, tools/, downloads/, opencode databases mounted under
# the XDG dirs.
#
# Why this isn't a one-shot copy: the previous "if [ ! -e
# WORKSPACE/.opencode ]; then cp -a once" pattern locks in whatever
# version of scripts/skills was current the FIRST time the container
# booted. After agent/scripts/lib/container.sh got the
# `runtime_mode == local` short-circuit in check_docker (newer than the
# stale workspace's March 2026 copy), every restart still saw the
# OLD container.sh shadowing the image's fix, which made check_docker
# falsely fail with "Docker is not installed" inside the all-in-one
# container. Re-sync per boot so image fixes propagate.
SYNC_DIRS=(scripts skills references .opencode docker)
for d in "${SYNC_DIRS[@]}"; do
  if [ -e "$TEMPLATE_DIR/$d" ]; then
    rm -rf "$WORKSPACE_DIR/$d"
    cp -a "$TEMPLATE_DIR/$d" "$WORKSPACE_DIR/"
  fi
done

# .env / .env.example are user-editable; only seed if absent.
for f in .env .env.example; do
  if [ ! -f "$WORKSPACE_DIR/$f" ] && [ -f "$TEMPLATE_DIR/$f" ]; then
    cp "$TEMPLATE_DIR/$f" "$WORKSPACE_DIR/$f"
  fi
done

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
