#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "https://www.okx.com",
  "hostname": "www.okx.com",
  "port": 443,
  "scope": ["www.okx.com", "*.okx.com"],
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
args=()
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
      args+=("$1")
      shift
      ;;
  esac
done

state_dir="$(cd "$(dirname "$0")" && pwd)"
count_file="$state_dir/invocation-count"
count=0
if [[ -f "$count_file" ]]; then
  count="$(cat "$count_file")"
fi
count=$((count + 1))
printf '%s' "$count" > "$count_file"

: > "$elog"

if [[ "$count" -eq 1 ]]; then
  : > "$output"
  for i in $(seq 1 10); do
    printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.okx.com/priapi/v1/dx/test/'"$i"'","tag":"js","attribute":"regex","source":"https://www.okx.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}' >> "$output"
    sleep 0.05
  done
  sleep 2
else
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.okx.com/en-sg","headers":{"Accept":"text/html"}},"response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}' >> "$output"
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.okx.com/priapi/v1/assistant/session/unread-message-count?t=1","headers":{"Accept":"application/json","X-Id-Group":"abc"}},"response":{"status_code":200,"headers":{"Content-Type":"application/json"}}}' >> "$output"
  printf '%s\n' '{"request":{"method":"POST","endpoint":"https://www.okx.com/apmfe/api/206/batch/envelope/?project_key=test","body":"{}","headers":{"Content-Type":"application/json;charset=UTF-8"}},"response":{"status_code":200,"headers":{"Content-Type":"application/octet-stream"}}}' >> "$output"
fi
EOF
chmod +x "$FAKE_KATANA"

REDTEAM_RUNTIME_MODE=local \
KATANA_LOCAL_BIN="$FAKE_KATANA" \
KATANA_FALLBACK_STALL_SECONDS=1 \
KATANA_FALLBACK_RECOVERABLE_THRESHOLD=8 \
KATANA_INGEST_EXIT_GRACE_SECONDS=1 \
KATANA_INGEST_POLL_SECONDS=0.2 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" > "$ENG_DIR/scans/katana_ingest.log" 2>&1

count_page="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url='https://www.okx.com/en-sg' AND source='katana';")"
if [[ "$count_page" != "1" ]]; then
  echo "FAIL: expected fallback HTML navigation row to stay katana, got $count_page" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source,url FROM cases ORDER BY id;" >&2
  exit 1
fi

count_api_get="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url='https://www.okx.com/priapi/v1/assistant/session/unread-message-count?t=1' AND source='katana-xhr';")"
if [[ "$count_api_get" != "1" ]]; then
  echo "FAIL: expected fallback JSON API GET to be relabeled as katana-xhr, got $count_api_get" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source,url FROM cases ORDER BY id;" >&2
  exit 1
fi

count_api_post="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url='https://www.okx.com/apmfe/api/206/batch/envelope/?project_key=test' AND source='katana-xhr';")"
if [[ "$count_api_post" != "1" ]]; then
  echo "FAIL: expected fallback POST API row to be relabeled as katana-xhr, got $count_api_post" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source,url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana fallback relabels browser-driven API rows as katana-xhr while leaving HTML navigation as katana"
