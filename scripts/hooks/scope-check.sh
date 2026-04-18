#!/bin/bash
# scope-check.sh — Claude Code PreToolUse hook
# Reads hook JSON from stdin, extracts hostnames from bash command,
# validates against scope.json. Exits 2 to block if out-of-scope.
# Hook format: {"tool_name":"Bash","tool_input":{"command":"..."}}
#
# Exit codes: 0 = allow, 2 = block

# No set -e: grep returning no matches (exit 1) is expected, not an error.

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/engagement.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/scope.sh"

# Only check Bash tool calls
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)
[ "$TOOL_NAME" != "Bash" ] && exit 0

# Extract command
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
[ -z "$COMMAND" ] && exit 0

# Skip local-only commands (no network traffic)
# Match first token of command (handles VAR=val && cmd, compound commands)
FIRST_TOKEN=$(echo "$COMMAND" | grep -oE '^[A-Za-z_][A-Za-z0-9_]*' 2>/dev/null || true)
case "$FIRST_TOKEN" in
  cat|ls|git|echo|test|mkdir|cp|mv|rm|jq|sqlite3|grep|sed|awk|sort|head|tail|chmod|source|export|read|DIR|ENG*|DB|DATE|TIME|HOSTNAME*|TARGET|PATH|PARENT*|BATCH*)
    exit 0 ;;
esac

# Also skip by first non-variable command in compound statements
case "$COMMAND" in
  *dispatcher.sh*|*ingest.sh*|*container.sh*|*schema.sql*) exit 0 ;;
  *"cat "*|*"mkdir "*|*"jq "*|*"sqlite3 "*|*"grep "*|*"sed "*) exit 0 ;;
esac

# Find active engagement directory
ENG_DIR=$(resolve_engagement_dir "$(pwd)" || true)
[ -z "$ENG_DIR" ] && exit 0
[ ! -f "$ENG_DIR/scope.json" ] && exit 0

# Extract allowed scope entries
mapfile -t SCOPE_LIST < <(scope_entries "$ENG_DIR")
[ "${#SCOPE_LIST[@]}" -eq 0 ] && exit 0

mapfile -t HOST_LIST < <(extract_command_hosts "$COMMAND")
[ "${#HOST_LIST[@]}" -eq 0 ] && exit 0

# Check each host against scope
for HOST in "${HOST_LIST[@]}"; do
  if ! host_in_scope "$HOST" "${SCOPE_LIST[@]}"; then
    AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "operator"' 2>/dev/null || echo "unknown")
    echo "BLOCKED: Host '$HOST' is not in scope. (agent: $AGENT_TYPE)" >&2
    echo "Allowed scope: ${SCOPE_LIST[*]}" >&2
    exit 2
  fi
done

exit 0
