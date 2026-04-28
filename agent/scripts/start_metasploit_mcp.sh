#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MCP_DIR="$ROOT_DIR/.opencode/vendor/MetasploitMCP"
VENV_DIR="$ROOT_DIR/.opencode/vendor/metasploitmcp-venv"
ENV_FILE="$ROOT_DIR/.env"
RUNTIME_CHECK="$ROOT_DIR/scripts/check_metasploit_runtime.sh"

if [ -f "$ENV_FILE" ] && { [ -z "${MSF_PASSWORD:-}" ] || [ -z "${MSF_SERVER:-}" ] || [ -z "${MSF_PORT:-}" ] || [ -z "${MSF_SSL:-}" ] || [ -z "${LOG_LEVEL:-}" ]; }; then
  set -a
  . "$ENV_FILE"
  set +a
fi

export MSF_USER="${MSF_USER:-msf}"
export MSF_PASSWORD="${MSF_PASSWORD:-msf}"
export MSF_SERVER="${MSF_SERVER:-127.0.0.1}"
export MSF_PORT="${MSF_PORT:-55553}"
export MSF_SSL="${MSF_SSL:-false}"
export LOG_LEVEL="${LOG_LEVEL:-${METASPLOIT_MCP_LOG_LEVEL:-info}}"

if [ ! -x "$VENV_DIR/bin/python" ] || [ ! -f "$MCP_DIR/MetasploitMCP.py" ]; then
  echo "MetasploitMCP runtime is not installed. Re-run ./install.sh opencode or scripts/install_metasploit_mcp.sh ." >&2
  exit 1
fi

"$RUNTIME_CHECK" --ensure-started >/dev/null

exec "$VENV_DIR/bin/python" "$MCP_DIR/MetasploitMCP.py" --transport stdio
