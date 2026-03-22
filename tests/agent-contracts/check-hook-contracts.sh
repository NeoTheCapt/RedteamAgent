#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agent"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/engagements/2026-03-23-120000-app"
cat > "$TMP_DIR/engagements/2026-03-23-120000-app/scope.json" <<'EOF'
{
  "hostname": "app.example.com",
  "scope": ["*.example.com"],
  "status": "in_progress"
}
EOF

printf '# log\n' > "$TMP_DIR/engagements/2026-03-23-120000-app/log.md"

INPUT='{"tool_name":"Bash","tool_input":{"command":"curl -s https://app.example.com/profile"}}'

if ! printf '%s' "$INPUT" | (cd "$TMP_DIR" && bash "$AGENT_DIR/scripts/hooks/scope-check.sh"); then
  echo "[FAIL] scope-check should allow primary hostname from scope.json.hostname" >&2
  exit 1
fi

printf '%s\n' "$TMP_DIR/engagements/2026-03-23-120000-app" > "$TMP_DIR/engagements/.active"

POST_INPUT='{
  "tool_name":"Bash",
  "agent_type":"operator",
  "tool_input":{"command":"nmap app.example.com"},
  "tool_response":{"stdout":"Host is up","exitCode":0}
}'

printf '%s' "$POST_INPUT" | (cd "$TMP_DIR" && bash "$AGENT_DIR/scripts/hooks/post-tool-log.sh")

if ! grep -q 'nmap app.example.com' "$TMP_DIR/engagements/2026-03-23-120000-app/log.md"; then
  echo "[FAIL] post-tool-log should write to active engagement log.md" >&2
  exit 1
fi

echo "[OK] Hook contracts hold"
