#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'pkill -f "$TMP_DIR/scripts/katana_ingest.sh" >/dev/null 2>&1 || true; pkill -f "$TMP_DIR/fake-katana.sh" >/dev/null 2>&1 || true; rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "status": "in_progress",
  "start_time": "2026-03-31T00:00:00Z",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat > "$TMP_DIR/fake-katana.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

output_file=""
error_file=""
uses_xhr=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      output_file="$2"
      shift 2
      ;;
    -elog)
      error_file="$2"
      shift 2
      ;;
    -xhr|-xhr-extraction|-system-chrome|-hh|-jc|-fx|-td|-tlsi|-duc)
      uses_xhr=1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$output_file" ]]; then
  echo "missing output file" >&2
  exit 1
fi

if [[ "$uses_xhr" -eq 1 ]]; then
  cat > "$output_file" <<'JSON'
{"timestamp":"2026-03-31T00:00:01Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/"},"error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}
{"timestamp":"2026-03-31T00:00:02Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/admin/application-configuration"},"error":"hybrid: response is nil"}
{"timestamp":"2026-03-31T00:00:03Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/api/profile"},"error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}
JSON
  : > "${error_file:-/dev/null}"
  sleep 30
  exit 0
fi

cat > "$output_file" <<'JSON'
{"timestamp":"2026-03-31T00:00:10Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}
{"timestamp":"2026-03-31T00:00:11Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/admin/application-configuration"},"response":{"status_code":200,"headers":{"Content-Type":"application/json"}}}
{"timestamp":"2026-03-31T00:00:12Z","request":{"method":"GET","endpoint":"http://127.0.0.1:8000/api/fallback-only"},"response":{"status_code":200,"headers":{"Content-Type":"application/json"}}}
JSON
: > "${error_file:-/dev/null}"
sleep 30
EOF
chmod +x "$TMP_DIR/fake-katana.sh"

(
  cd "$ROOT"
  REDTEAM_RUNTIME_MODE=local \
  KATANA_LOCAL_BIN="$TMP_DIR/fake-katana.sh" \
  KATANA_FALLBACK_STALL_SECONDS=1 \
  KATANA_FALLBACK_RECOVERABLE_THRESHOLD=2 \
  KATANA_INGEST_POLL_SECONDS=1 \
  agent/scripts/katana_ingest.sh "$ENG_DIR" >"$TMP_DIR/katana_ingest.stdout" 2>"$TMP_DIR/katana_ingest.stderr" &
  echo $! > "$TMP_DIR/katana_ingest.pid"
)

KATANA_INGEST_PID="$(cat "$TMP_DIR/katana_ingest.pid")"

for _ in $(seq 1 15); do
  total_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
  if sqlite3 "$ENG_DIR/cases.db" 'select url from cases where url = "http://127.0.0.1:8000/api/fallback-only" limit 1;' | grep -qx 'http://127.0.0.1:8000/api/fallback-only'; then
    break
  fi
  if [[ "${total_cases:-0}" -ge 4 ]]; then
    break
  fi
  sleep 1
done

kill "$KATANA_INGEST_PID" 2>/dev/null || true
wait "$KATANA_INGEST_PID" 2>/dev/null || true

total_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$total_cases" -ge 4 ]] || {
  echo "expected katana fallback to populate queue, got $total_cases cases" >&2
  echo "--- stdout ---" >&2
  sed -n '1,160p' "$TMP_DIR/katana_ingest.stdout" >&2 || true
  echo "--- stderr ---" >&2
  sed -n '1,160p' "$TMP_DIR/katana_ingest.stderr" >&2 || true
  exit 1
}

sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -qx 'http://127.0.0.1:8000/rest/admin/application-configuration'
sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -qx 'http://127.0.0.1:8000/api/fallback-only'

if ! grep -q 'fallback' "$TMP_DIR/katana_ingest.stdout"; then
  echo "expected katana ingest stdout to mention fallback activation" >&2
  sed -n '1,160p' "$TMP_DIR/katana_ingest.stdout" >&2 || true
  exit 1
fi

echo "katana fallback contracts: ok"
