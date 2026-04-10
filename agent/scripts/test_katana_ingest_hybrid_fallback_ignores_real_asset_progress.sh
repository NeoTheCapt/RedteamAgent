#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "https://www.example.com",
  "hostname": "www.example.com",
  "port": 443,
  "scope": ["www.example.com", "*.example.com"],
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

  for i in $(seq 1 7); do
    printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/priapi/v1/dx/test/'"$i"'","tag":"js","attribute":"regex","source":"https://www.example.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}' >> "$output"
    sleep 0.05
  done

  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/cdn/assets/app.js","tag":"script","attribute":"src","source":"https://www.example.com/en-sg"},"response":{"status_code":200,"headers":{"Content-Type":"application/javascript"}}}' >> "$output"

  for i in $(seq 8 14); do
    printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/priapi/v1/dx/test/'"$i"'","tag":"js","attribute":"regex","source":"https://www.example.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}' >> "$output"
    sleep 0.05
  done

  sleep 2
else
  printf '%s\0' "${args[@]}" > "$state_dir/second-args.bin"
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/en-sg","tag":"navigation","attribute":"visit","source":"https://www.example.com/en-sg"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"},"xhr_requests":[{"method":"GET","endpoint":"https://www.example.com/api/v5/market/tickers?instType=SPOT","source":"https://www.example.com/en-sg","headers":{"Content-Type":"application/json"}}]}}' >> "$output"
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

if ! rg -n 'Activating headless katana fallback' "$ENG_DIR/scans/katana_ingest.log" >/dev/null 2>&1; then
  echo "FAIL: fallback did not activate when hybrid only made asset progress and zero katana-xhr discoveries" >&2
  cat "$ENG_DIR/scans/katana_ingest.log" >&2
  exit 1
fi

if ! [[ -f "$TMP_DIR/second-args.bin" ]]; then
  echo "FAIL: fallback never launched a second katana pass" >&2
  cat "$ENG_DIR/scans/katana_ingest.log" >&2 || true
  exit 1
fi

count_js="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/cdn/assets/app.js' AND source = 'katana';")"
if [[ "$count_js" != "1" ]]; then
  echo "FAIL: expected the 200 JS asset row to be ingested once, got $count_js" >&2
  exit 1
fi

count_xhr="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/api/v5/market/tickers?instType=SPOT' AND source = 'katana-xhr';")"
if [[ "$count_xhr" != "1" ]]; then
  echo "FAIL: expected fallback crawl to ingest one katana-xhr row after asset-only progress, got $count_xhr" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana ingest falls back when hybrid only makes asset progress and never lands katana-xhr discoveries"
