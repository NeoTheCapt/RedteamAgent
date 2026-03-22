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
SCOPE=$(jq -r '([.hostname] + (.scope // [])) | map(select(type == "string" and . != "")) | unique[]' "$ENG_DIR/scope.json" 2>/dev/null || true)
[ -z "$SCOPE" ] && exit 0

# Extract hostnames/IPs from the command
HOSTS=$(echo "$COMMAND" | grep -oE '(https?://)?[a-zA-Z0-9]([a-zA-Z0-9\-]*\.)+[a-zA-Z]{2,}(:[0-9]+)?' 2>/dev/null | \
  sed 's|https\?://||' | sed 's|:[0-9]*$||' | sort -u || true)

IPS=$(echo "$COMMAND" | grep -oE '[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' 2>/dev/null | sort -u || true)

# If no hosts or IPs found, allow (local command)
[ -z "$HOSTS" ] && [ -z "$IPS" ] && exit 0

# Check each host against scope
for HOST in $HOSTS $IPS; do
  IN_SCOPE=false

  # Always allow localhost/loopback
  case "$HOST" in
    localhost|127.0.0.1|0.0.0.0|::1) continue ;;
  esac

  for ALLOWED in $SCOPE; do
    if [ "$HOST" = "$ALLOWED" ]; then
      IN_SCOPE=true
      break
    fi
    # Wildcard: *.domain matches any subdomain
    WILDCARD_DOMAIN=$(echo "$ALLOWED" | sed 's/^\*\.//')
    if [ "$ALLOWED" != "$WILDCARD_DOMAIN" ]; then
      case "$HOST" in
        *".$WILDCARD_DOMAIN") IN_SCOPE=true; break ;;
        "$WILDCARD_DOMAIN") IN_SCOPE=true; break ;;
      esac
    fi
  done

  if [ "$IN_SCOPE" = false ]; then
    AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "operator"' 2>/dev/null || echo "unknown")
    echo "BLOCKED: Host '$HOST' is not in scope. (agent: $AGENT_TYPE)" >&2
    echo "Allowed scope: $SCOPE" >&2
    exit 2
  fi
done

exit 0
