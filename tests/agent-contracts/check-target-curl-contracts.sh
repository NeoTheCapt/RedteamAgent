#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HOOK_SCRIPT="$ROOT_DIR/agent/scripts/hooks/post-tool-log.sh"
CHECK_SCRIPT="$ROOT_DIR/agent/scripts/check_target_curl_usage.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_script() {
  [[ -x "$1" ]] || fail "missing executable script: $1"
}

make_engagement_dir() {
  local root dir
  root=$(mktemp -d "${TMPDIR:-/tmp}/target-curl.XXXXXX")
  dir="$root/engagements/2026-03-23-000000-127-0-0-1"
  mkdir -p "$dir"
  cat >"$dir/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "mode": "ctf",
  "status": "in_progress",
  "start_time": "2026-03-23T00:00:00Z",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF
  cat >"$dir/log.md" <<'EOF'
# Engagement Log

- **Target**: http://127.0.0.1:8000
- **Date**: 2026-03-23
- **Mode**: CTF
- **Status**: In Progress

---
EOF
  printf '%s\n' "$dir" >"$root/engagements/.active"
  printf '%s\n' "$root"
}

run_hook() {
  local root="$1"
  local command="$2"
  (
    cd "$root"
    printf '{"tool_name":"Bash","agent_type":"vulnerability-analyst","tool_input":{"command":"%s"},"tool_response":{"stdout":"","exitCode":0}}\n' "$command" | bash "$HOOK_SCRIPT"
  )
}

test_only_in_scope_raw_curl_warns() {
  local root dir
  root=$(make_engagement_dir)
  dir="$root/engagements/2026-03-23-000000-127-0-0-1"

  run_hook "$root" '/usr/bin/curl -sS http://127.0.0.1:8000/api/Users'
  rg 'In-scope raw curl bypassed `run_tool curl`' "$dir/log.md" >/dev/null || fail "missing warning for in-scope raw curl"
  if "$CHECK_SCRIPT" "$dir" >/dev/null 2>&1; then
    fail "check_target_curl_usage.sh should fail when warning exists"
  fi

  cat >"$dir/log.md" <<'EOF'
# Engagement Log

- **Target**: http://127.0.0.1:8000
- **Date**: 2026-03-23
- **Mode**: CTF
- **Status**: In Progress

---
EOF
  run_hook "$root" 'run_tool curl -sS http://127.0.0.1:8000/api/Users'
  if rg 'In-scope raw curl bypassed `run_tool curl`' "$dir/log.md" >/dev/null; then
    fail "run_tool curl should not trigger warning"
  fi

  run_hook "$root" '/usr/bin/curl -sS https://example.com/'
  if rg 'In-scope raw curl bypassed `run_tool curl`' "$dir/log.md" >/dev/null; then
    fail "external raw curl should not trigger warning"
  fi
  "$CHECK_SCRIPT" "$dir" >/dev/null || fail "check_target_curl_usage.sh should pass without warning"

  rm -rf "$root"
}

main() {
  need_script "$HOOK_SCRIPT"
  need_script "$CHECK_SCRIPT"
  test_only_in_scope_raw_curl_warns
  echo "target curl contracts: ok"
}

main "$@"
