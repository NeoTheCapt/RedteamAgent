#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! rg -q --fixed-strings "$pattern" "$file"; then
    echo "[FAIL] Missing pattern in $file: $pattern" >&2
    return 1
  fi
}

assert_file_exists() {
  local path="$1"
  if [ ! -e "$path" ]; then
    echo "[FAIL] Missing file: $path" >&2
    return 1
  fi
}

assert_file_exists "$REPO_ROOT/agent/docker/metasploit/Dockerfile"
assert_contains "$REPO_ROOT/agent/docker/docker-compose.yml" "metasploit:"
assert_contains "$REPO_ROOT/agent/.opencode/opencode.json" '"metasploit": {'
assert_contains "$REPO_ROOT/agent/.opencode/prompts/agents/exploit-developer.txt" "Metasploit"
assert_contains "$REPO_ROOT/agent/scripts/start_metasploit_mcp.sh" ".env"
assert_contains "$REPO_ROOT/agent/scripts/start_metasploit_mcp.sh" "LOG_LEVEL"

echo "[OK] MetasploitMCP contracts are present"
