#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CONTAINER_LIB="$ROOT_DIR/agent/scripts/lib/container.sh"
RTCURL_TEMPLATE="$ROOT_DIR/agent/scripts/templates/rtcurl.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

make_engagement_dir() {
  local root dir
  root=$(mktemp -d "${TMPDIR:-/tmp}/localhost-runtime.XXXXXX")
  dir="$root/engagements/2026-03-28-000000-127-0-0-1"
  mkdir -p "$dir/tools" "$dir/scans" "$dir/pids"
  cat >"$dir/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "status": "in_progress",
  "start_time": "2026-03-28T00:00:00Z",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF
  cat >"$dir/auth.json" <<'EOF'
{}
EOF
  cat >"$dir/user-agent.txt" <<'EOF'
Localhost-Contract-Test
EOF
  printf '%s\n' "$dir"
}

test_container_rewrite_helpers() {
  local dir rewritten_host rewritten_url scope_args
  dir=$(make_engagement_dir)
  ENGAGEMENT_DIR="$dir"
  # shellcheck disable=SC1090
  source "$CONTAINER_LIB"

  rewritten_host="$(_rewrite_runtime_target_arg '127.0.0.1')"
  [[ "$rewritten_host" == 'host.docker.internal' ]] || fail "expected loopback host rewrite, got: $rewritten_host"

  rewritten_url="$(_rewrite_runtime_target_arg 'http://127.0.0.1:8000/api/Users?limit=5')"
  [[ "$rewritten_url" == 'http://host.docker.internal:8000/api/Users?limit=5' ]] || fail "expected loopback URL rewrite, got: $rewritten_url"

  scope_args="$(_katana_scope_args | tr '\0' '\n')"
  printf '%s\n' "$scope_args" | rg -F 'host\.docker\.internal' >/dev/null || fail 'expected katana scope args to include host.docker.internal'

  rm -rf "$(dirname "$(dirname "$dir")")"
}

test_run_tool_local_rewrites_loopback_urls() {
  local dir fakebin output
  dir=$(make_engagement_dir)
  fakebin=$(mktemp -d "${TMPDIR:-/tmp}/localhost-runtime-bin.XXXXXX")
  output="$fakebin/whatweb.args"

  cat >"$fakebin/whatweb" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@"
EOF
  chmod +x "$fakebin/whatweb"

  ENGAGEMENT_DIR="$dir"
  REDTEAM_RUNTIME_MODE=local
  PATH="$fakebin:$PATH"
  # shellcheck disable=SC1090
  source "$CONTAINER_LIB"

  run_tool whatweb 'http://127.0.0.1:8000/login' >"$output"
  rg -F 'http://host.docker.internal:8000/login' "$output" >/dev/null || fail 'run_tool did not rewrite loopback URL for local runtime'

  rm -rf "$fakebin" "$(dirname "$(dirname "$dir")")"
}

test_rtcurl_rewrites_in_scope_loopback_urls() {
  local dir fakebin output rtcurl
  dir=$(make_engagement_dir)
  fakebin=$(mktemp -d "${TMPDIR:-/tmp}/localhost-runtime-curl.XXXXXX")
  output="$fakebin/curl.args"
  rtcurl="$dir/tools/rtcurl"

  cat >"$fakebin/curl" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" > "$output"
EOF
  chmod +x "$fakebin/curl"
  cp "$RTCURL_TEMPLATE" "$rtcurl"
  chmod +x "$rtcurl"

  PATH="$fakebin:$PATH" \
  RTCURL_AUTH_FILE="$dir/auth.json" \
  RTCURL_SCOPE_FILE="$dir/scope.json" \
  RTCURL_USER_AGENT_FILE="$dir/user-agent.txt" \
    "$rtcurl" -sS 'http://127.0.0.1:8000/api/Users?offset=0'

  rg -F 'http://host.docker.internal:8000/api/Users?offset=0' "$output" >/dev/null || fail 'rtcurl did not rewrite loopback URL to host gateway alias'

  rm -rf "$fakebin" "$(dirname "$(dirname "$dir")")"
}

main() {
  [[ -f "$CONTAINER_LIB" ]] || fail "missing container lib"
  [[ -f "$RTCURL_TEMPLATE" ]] || fail "missing rtcurl template"
  test_container_rewrite_helpers
  test_run_tool_local_rewrites_loopback_urls
  test_rtcurl_rewrites_in_scope_loopback_urls
  echo 'localhost runtime contracts: ok'
}

main "$@"
