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
{
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.okx.com/en-sg","tag":"navigation","attribute":"visit","source":"https://www.okx.com/en-sg"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}'
  printf '%s\n' '{not-json'
  printf '%s\n' '{"request":{"method":"GET","endpoint":"https://www.okx.com/priapi/v1/dx/market/v2/token/pool/project/list","tag":"js","attribute":"regex","source":"https://www.okx.com/cdn/assets/app.js"},"error":"hybrid: response is nil"}'
} > "$output"
EOF
chmod +x "$FAKE_KATANA"

REDTEAM_RUNTIME_MODE=local \
KATANA_LOCAL_BIN="$FAKE_KATANA" \
KATANA_INGEST_EXIT_GRACE_SECONDS=1 \
KATANA_INGEST_POLL_SECONDS=0.1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" > "$ENG_DIR/scans/katana_ingest.log" 2>&1

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
assert len(rows) == 2, rows
assert rows[0]["request"]["endpoint"] == "https://www.okx.com/en-sg", rows
assert rows[1]["request"]["endpoint"] == "https://www.okx.com/priapi/v1/dx/market/v2/token/pool/project/list", rows
PY

count_total="$(sqlite3 "$ENG_DIR/cases.db" 'SELECT COUNT(*) FROM cases;')"
if [[ "$count_total" != "2" ]]; then
  echo "FAIL: expected malformed newline-delimited katana row to be skipped without stopping later rows; got $count_total cases" >&2
  sqlite3 "$ENG_DIR/cases.db" 'SELECT source, url FROM cases ORDER BY id;' >&2
  exit 1
fi

if ! rg -n 'Skipping malformed katana JSON row during public artifact sanitization' "$ENG_DIR/scans/katana_ingest.log" >/dev/null 2>&1; then
  echo "FAIL: expected malformed-row skip warning in katana_ingest.log" >&2
  cat "$ENG_DIR/scans/katana_ingest.log" >&2
  exit 1
fi

echo "PASS: katana_ingest skips malformed newline-delimited JSON rows without aborting later ingestion"
