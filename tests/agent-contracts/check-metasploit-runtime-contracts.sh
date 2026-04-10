#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
HELPER="$REPO_ROOT/agent/scripts/check_metasploit_runtime.sh"

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! rg -q --fixed-strings -- "$pattern" "$file"; then
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

fake_docker_setup() {
  local tmp_dir="$1"
  local state_file="$2"
  local log_file="$3"
  mkdir -p "$tmp_dir/bin"
  cat > "$tmp_dir/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

state_file="${FAKE_MSF_STATE_FILE:?}"
log_file="${FAKE_DOCKER_LOG:?}"

echo "docker $*" >> "$log_file"

case "$1" in
  info)
    exit 0
    ;;
  inspect)
    if [ "${2:-}" = "-f" ]; then
      if [ -f "$state_file" ] && [ "$(cat "$state_file")" = "running" ]; then
        echo true
      else
        echo false
      fi
      exit 0
    fi
    ;;
  compose)
    shift
    if [ "${1:-}" = "-f" ]; then
      shift 2
    fi
    case "${1:-}" in
      ps)
        if [ -f "$state_file" ] && [ "$(cat "$state_file")" = "running" ]; then
          echo metasploit-fake-id
        fi
        ;;
      up)
        if [ "${2:-}" = "metasploit" ] || [ "${1:-}" = "up" ]; then
          printf '%s' running > "$state_file"
        fi
        ;;
    esac
    exit 0
    ;;
esac

exit 0
EOF
  chmod +x "$tmp_dir/bin/docker"
}

assert_file_exists "$HELPER"
assert_contains "$HELPER" "--ensure"
assert_contains "$HELPER" "--ensure-started"
assert_contains "$HELPER" 'compose up -d "$SERVICE_NAME"'

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

# Docker missing should fail cleanly.
mkdir -p "$tmp_dir/empty"
if PATH="$tmp_dir/empty" /bin/bash "$HELPER" >/dev/null 2>"$tmp_dir/no-docker.err"; then
  echo "[FAIL] helper unexpectedly succeeded without docker" >&2
  exit 1
fi
if ! rg -q 'docker not available|Docker is not installed' "$tmp_dir/no-docker.err"; then
  echo "[FAIL] missing docker-unavailable error" >&2
  cat "$tmp_dir/no-docker.err" >&2
  exit 1
fi

# Runtime stopped should fail without --ensure.
fake_docker_setup "$tmp_dir" "$tmp_dir/state" "$tmp_dir/docker.log"
printf '%s' stopped > "$tmp_dir/state"
if PATH="$tmp_dir/bin:$PATH" FAKE_MSF_STATE_FILE="$tmp_dir/state" FAKE_DOCKER_LOG="$tmp_dir/docker.log" "$HELPER" >/dev/null 2>"$tmp_dir/stopped.err"; then
  echo "[FAIL] helper unexpectedly succeeded with a stopped runtime" >&2
  exit 1
fi
assert_contains "$tmp_dir/stopped.err" "Metasploit runtime is not running"

# Runtime stopped should recover with --ensure-started and mark service running.
if ! PATH="$tmp_dir/bin:$PATH" FAKE_MSF_STATE_FILE="$tmp_dir/state" FAKE_DOCKER_LOG="$tmp_dir/docker.log" METASPLOIT_RUNTIME_SKIP_PORT_PROBE=1 "$HELPER" --ensure-started >/dev/null 2>"$tmp_dir/ensure.err"; then
  echo "[FAIL] helper failed to recover the runtime" >&2
  cat "$tmp_dir/ensure.err" >&2
  exit 1
fi
assert_contains "$tmp_dir/docker.log" "docker compose -f"
assert_contains "$tmp_dir/docker.log" "up -d metasploit"
assert_contains "$tmp_dir/ensure.err" "Runtime unavailable, starting metasploit"

# Running runtime should succeed without recovery.
printf '%s' running > "$tmp_dir/state"
if ! PATH="$tmp_dir/bin:$PATH" FAKE_MSF_STATE_FILE="$tmp_dir/state" FAKE_DOCKER_LOG="$tmp_dir/docker.log" METASPLOIT_RUNTIME_SKIP_PORT_PROBE=1 "$HELPER" >/dev/null; then
  echo "[FAIL] helper failed for a running runtime" >&2
  exit 1
fi

# Local runtime mode should use pid-based process management, not docker.
cat > "$tmp_dir/bin/fake-msfrpcd" <<'EOF'
#!/usr/bin/env bash
sleep 30
EOF
chmod +x "$tmp_dir/bin/fake-msfrpcd"

rm -f "$tmp_dir/docker.log"
if PATH="$tmp_dir/bin:$PATH" REDTEAM_RUNTIME_MODE=local METASPLOIT_PID_DIR="$tmp_dir/local-pids" METASPLOIT_LOCAL_CMD="$tmp_dir/bin/fake-msfrpcd" METASPLOIT_RUNTIME_SKIP_PORT_PROBE=1 "$HELPER" --ensure-started >/dev/null 2>"$tmp_dir/local.err"; then
  :
else
  echo "[FAIL] local runtime ensure-started failed" >&2
  cat "$tmp_dir/local.err" >&2
  exit 1
fi

if [ -f "$tmp_dir/docker.log" ]; then
  echo "[FAIL] local runtime should not call docker" >&2
  cat "$tmp_dir/docker.log" >&2
  exit 1
fi

local_pid_file="$tmp_dir/local-pids/metasploit.pid"
assert_file_exists "$local_pid_file"
local_pid=$(cat "$local_pid_file")
kill -0 "$local_pid"
kill "$local_pid" 2>/dev/null || true
wait "$local_pid" 2>/dev/null || true

echo "[OK] Metasploit runtime contract checks passed"
