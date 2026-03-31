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
  for i in $(seq 1 14); do
    printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/priapi/v1/dx/test/'"$i"'","tag":"js","attribute":"regex","source":"https://www.example.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}' >> "$output"
  done
  printf '%s' '{"request":{"method":"GET","endpoint":"https://www.example.com/broken-tail","tag":"file","attribute":"robotstxt","source":"https://www.example.com/robots.txt"},"response":{"status_code":404' >> "$output"
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

if ! [[ -f "$TMP_DIR/second-args.bin" ]]; then
  echo "FAIL: fallback never launched a second katana pass" >&2
  cat "$ENG_DIR/scans/katana_ingest.log" >&2 || true
  exit 1
fi

python3 - <<'PY' "$TMP_DIR/second-args.bin"
from pathlib import Path
import sys
args = Path(sys.argv[1]).read_bytes().split(b'\0')
args = [a.decode('utf-8') for a in args if a]
required = {'-xhr', '-xhr-extraction', '-system-chrome', '-headless-options'}
missing = sorted(required.difference(args))
if missing:
    raise SystemExit(f"FAIL: fallback args missing expected entries: {missing}\nargs={args}")
if '-hh' in args:
    raise SystemExit(f"FAIL: fallback args should disable hybrid mode but kept -hh\nargs={args}")
PY

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
for lineno, line in enumerate(path.read_text().splitlines(), 1):
    if not line.strip():
        continue
    json.loads(line)
PY

count_xhr="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/api/v5/market/tickers?instType=SPOT' AND source = 'katana-xhr';")"
if [[ "$count_xhr" != "1" ]]; then
  echo "FAIL: expected fallback crawl to ingest one katana-xhr row, got $count_xhr" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

if [[ ! -s "$ENG_DIR/scans/katana_output.jsonl.partial-pre-fallback" ]]; then
  echo "FAIL: expected invalid pre-fallback tail to be preserved separately" >&2
  exit 1
fi

echo "PASS: katana fallback keeps XHR/headless enabled and sanitizes partial output before restart"
