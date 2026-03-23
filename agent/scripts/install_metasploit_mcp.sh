#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-}"
if [ -z "$TARGET_DIR" ]; then
  echo "Usage: $0 <target_dir>" >&2
  exit 1
fi

MCP_REPO_URL="https://github.com/GH05TCREW/MetasploitMCP.git"
MCP_DIR="$TARGET_DIR/.opencode/vendor/MetasploitMCP"
VENV_DIR="$TARGET_DIR/.opencode/vendor/metasploitmcp-venv"

rm -rf "$MCP_DIR" "$VENV_DIR"
mkdir -p "$(dirname "$MCP_DIR")"

git clone --depth 1 "$MCP_REPO_URL" "$MCP_DIR" >/dev/null 2>&1
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install --quiet -r "$MCP_DIR/requirements.txt"

echo "$MCP_DIR"
