#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

eng_dir="$tmp_dir/engagement"
mkdir -p "$eng_dir/pids" "$eng_dir/scans" "$tmp_dir/bin"

cat > "$eng_dir/scope.json" <<'EOF'
{
  "target": "https://example.test",
  "hostname": "example.test",
  "scope": ["example.test", "*.example.test"]
}
EOF

cat > "$eng_dir/.env" <<'EOF'
TEST_LOCAL_ENV=from-engagement-env
EOF

cat > "$tmp_dir/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker should not be called in local mode" >&2
exit 99
EOF
chmod +x "$tmp_dir/bin/docker"

cat > "$tmp_dir/bin/fake-tool" <<'EOF'
#!/usr/bin/env bash
printf 'tool:%s\n' "$*" > "${ENGAGEMENT_DIR}/scans/run_tool.out"
printf 'env:%s\n' "${TEST_LOCAL_ENV:-missing}" >> "${ENGAGEMENT_DIR}/scans/run_tool.out"
EOF
chmod +x "$tmp_dir/bin/fake-tool"

cat > "$tmp_dir/bin/fake-mitmproxy" <<'EOF'
#!/usr/bin/env bash
printf 'proxy:%s\n' "$*" > "${ENGAGEMENT_DIR}/scans/proxy.invocation"
sleep 30
EOF
chmod +x "$tmp_dir/bin/fake-mitmproxy"

cat > "$tmp_dir/bin/fake-katana" <<'EOF'
#!/usr/bin/env bash
printf 'katana:%s\n' "$*" > "${ENGAGEMENT_DIR}/scans/katana.invocation"
sleep 30
EOF
chmod +x "$tmp_dir/bin/fake-katana"

export PATH="$tmp_dir/bin:$PATH"
export ENGAGEMENT_DIR="$eng_dir"
export REDTEAM_RUNTIME_MODE=local
export MITMPROXY_BIN="$tmp_dir/bin/fake-mitmproxy"
export KATANA_LOCAL_BIN="$tmp_dir/bin/fake-katana"

source "$REPO_ROOT/agent/scripts/lib/container.sh"

wait_for_file() {
  local path="$1"
  local i
  for i in $(seq 1 20); do
    [ -f "$path" ] && return 0
    sleep 0.1
  done
  echo "[FAIL] Timed out waiting for file: $path" >&2
  return 1
}

run_tool fake-tool alpha beta
grep -q 'tool:alpha beta' "$eng_dir/scans/run_tool.out"
grep -q 'env:from-engagement-env' "$eng_dir/scans/run_tool.out"

start_proxy --listen-port 8080
wait_for_file "$eng_dir/scans/proxy.invocation"
test -f "$eng_dir/pids/proxy.pid"
proxy_pid=$(cat "$eng_dir/pids/proxy.pid")
kill -0 "$proxy_pid"

start_katana "http://example.test"
wait_for_file "$eng_dir/scans/katana.invocation"
test -f "$eng_dir/pids/katana.pid"
katana_pid=$(cat "$eng_dir/pids/katana.pid")
kill -0 "$katana_pid"
grep -q -- '-hh' "$eng_dir/scans/katana.invocation"
grep -q -- '-jc' "$eng_dir/scans/katana.invocation"
grep -q -- '-xhr-extraction' "$eng_dir/scans/katana.invocation"
grep -q -- '-fx' "$eng_dir/scans/katana.invocation"
grep -q -- '-td' "$eng_dir/scans/katana.invocation"
grep -q -- '-kf all' "$eng_dir/scans/katana.invocation"
grep -q -- '-iqp' "$eng_dir/scans/katana.invocation"
grep -q -- '-fsu' "$eng_dir/scans/katana.invocation"
if grep -q -- '-pc' "$eng_dir/scans/katana.invocation"; then
  echo "[FAIL] path-climb should be opt-in for start_katana default args" >&2
  exit 1
fi
grep -Fq -- '-tlsi' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-duc' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-ns' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-s breadth-first' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-d 8' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-ct 15m' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-timeout 20' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-time-stable 5' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-retry 3' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-mfc 20' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-c 15' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-p 4' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-rl 60' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-cs ^https?://example\.test([/:?#]|$)' "$eng_dir/scans/katana.invocation"
grep -Fq -- '-cs ^https?://([^.]+\.)*example\.test([/:?#]|$)' "$eng_dir/scans/katana.invocation"
grep -q -- '-system-chrome' "$eng_dir/scans/katana.invocation"
grep -q -- '-system-chrome-path /usr/bin/chromium' "$eng_dir/scans/katana.invocation"
grep -q -- '-omit-raw' "$eng_dir/scans/katana.invocation"
grep -q -- '-omit-body' "$eng_dir/scans/katana.invocation"
grep -q -- '-jsonl' "$eng_dir/scans/katana.invocation"
grep -q -- '-silent' "$eng_dir/scans/katana.invocation"

stop_all_containers

if kill -0 "$proxy_pid" 2>/dev/null; then
  echo "[FAIL] proxy pid still running after stop" >&2
  exit 1
fi
if kill -0 "$katana_pid" 2>/dev/null; then
  echo "[FAIL] katana pid still running after stop" >&2
  exit 1
fi

rm -f "$eng_dir/scans/katana.invocation"
export KATANA_ENABLE_PATH_CLIMB=1
start_katana "http://example.test"
wait_for_file "$eng_dir/scans/katana.invocation"
grep -q -- '-pc' "$eng_dir/scans/katana.invocation"
stop_katana

echo "[OK] container local runtime contracts passed"
