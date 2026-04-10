#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://host.docker.internal:8000",
  "hostname": "host.docker.internal",
  "port": 8000,
  "scope": ["host.docker.internal", "*.host.docker.internal"],
  "status": "in_progress",
  "current_phase": "collect"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

FAKE_KATANA="$TMP_DIR/fake-katana.sh"
cat > "$FAKE_KATANA" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output=""
elog=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      output="$2"
      shift 2
      ;;
    -elog)
      elog="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

: > "$elog"
cat > "$output" <<'JSON'
{"request":{"method":"GET","endpoint":"http://host.docker.internal:8000/api/profile","source":"http://host.docker.internal:8000/main.js"},"response":{"status_code":200,"headers":{"Content-Type":"application/json"},"xhr_requests":[{"method":"GET","endpoint":"http://host.docker.internal:8000/api/settings","source":"http://host.docker.internal:8000/main.js","headers":{"Content-Type":"application/json"}}]}}
JSON
EOF
chmod +x "$FAKE_KATANA"

REDTEAM_RUNTIME_MODE=local \
KATANA_LOCAL_BIN="$FAKE_KATANA" \
KATANA_INGEST_EXIT_GRACE_SECONDS=1 \
KATANA_INGEST_POLL_SECONDS=1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null &
katana_ingest_pid=$!

for _ in {1..15}; do
  if ! kill -0 "$katana_ingest_pid" 2>/dev/null; then
    wait "$katana_ingest_pid"
    katana_ingest_pid=""
    break
  fi
  sleep 1
done

if [[ -n "${katana_ingest_pid:-}" ]] && kill -0 "$katana_ingest_pid" 2>/dev/null; then
  kill "$katana_ingest_pid" 2>/dev/null || true
  wait "$katana_ingest_pid" 2>/dev/null || true
  echo "FAIL: katana_ingest.sh did not exit after katana finished" >&2
  exit 1
fi

count_api="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/api/profile' AND source = 'katana';")"
count_xhr="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/api/settings' AND source = 'katana-xhr';")"

if [[ "$count_api" != "1" ]]; then
  echo "FAIL: expected katana request to be ingested once, got $count_api" >&2
  exit 1
fi

if [[ "$count_xhr" != "1" ]]; then
  echo "FAIL: expected katana-xhr request to be ingested once, got $count_xhr" >&2
  exit 1
fi

if [[ -f "$ENG_DIR/pids/katana.pid" ]]; then
  echo "FAIL: katana pid file should be cleaned up on exit" >&2
  exit 1
fi

if [[ -f "$ENG_DIR/pids/katana_ingest.pid" ]]; then
  echo "FAIL: katana_ingest pid file should be cleaned up on exit" >&2
  exit 1
fi

echo "PASS: katana_ingest exits after katana finishes and keeps katana/katana-xhr rows"
