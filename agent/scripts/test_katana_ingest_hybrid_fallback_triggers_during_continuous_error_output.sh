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
  trap 'exit 0' TERM INT
  i=0
  while true; do
    i=$((i + 1))
    printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/priapi/v1/dx/test/'"$i"'","tag":"js","attribute":"regex","source":"https://www.example.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}' >> "$output"
    sleep 0.15
  done
else
  printf '%s\0' "${args[@]}" > "$state_dir/second-args.bin"
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.example.com/en-sg","tag":"navigation","attribute":"visit","source":"https://www.example.com/en-sg"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"},"xhr_requests":[{"method":"GET","endpoint":"https://www.example.com/api/v5/market/tickers?instType=SPOT","source":"https://www.example.com/en-sg","headers":{"Content-Type":"application/json"}}]}}' >> "$output"
fi
EOF
chmod +x "$FAKE_KATANA"

python3 - <<'PY' "$ROOT" "$ENG_DIR" "$FAKE_KATANA"
import subprocess
import sys
root, eng_dir, fake_katana = sys.argv[1:4]
env = dict(
    REDTEAM_RUNTIME_MODE='local',
    KATANA_LOCAL_BIN=fake_katana,
    KATANA_FALLBACK_STALL_SECONDS='1',
    KATANA_FALLBACK_RECOVERABLE_THRESHOLD='8',
    KATANA_INGEST_EXIT_GRACE_SECONDS='1',
    KATANA_INGEST_POLL_SECONDS='0.1',
)
cmd = [f'{root}/agent/scripts/katana_ingest.sh', eng_dir]
with open(f'{eng_dir}/scans/katana_ingest.log', 'w', encoding='utf-8') as log:
    subprocess.run(cmd, env={**subprocess.os.environ, **env}, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=6)
PY

if ! [[ -f "$TMP_DIR/second-args.bin" ]]; then
  echo "FAIL: fallback never launched a second katana pass while errors were still streaming" >&2
  cat "$ENG_DIR/scans/katana_ingest.log" >&2 || true
  exit 1
fi

count_xhr="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/api/v5/market/tickers?instType=SPOT' AND source = 'katana-xhr';")"
if [[ "$count_xhr" != "1" ]]; then
  echo "FAIL: expected continuous-error fallback crawl to ingest one katana-xhr row, got $count_xhr" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana fallback triggers even when recoverable hybrid errors keep appending output"
