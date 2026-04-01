#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
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
printf '%s\n' '{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/","tag":"navigation","attribute":"visit","source":"http://127.0.0.1:8000/"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}' > "$output"
printf '%s' '{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/user/login"' >> "$output"
EOF
chmod +x "$FAKE_KATANA"

REDTEAM_RUNTIME_MODE=local \
KATANA_LOCAL_BIN="$FAKE_KATANA" \
KATANA_INGEST_EXIT_GRACE_SECONDS=1 \
KATANA_INGEST_POLL_SECONDS=0.2 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" > "$ENG_DIR/scans/katana_ingest.log" 2>&1

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
assert len(rows) == 1, rows
assert rows[0]["request"]["endpoint"] == "http://127.0.0.1:8000/"
PY

if [[ ! -s "$ENG_DIR/scans/katana_output.jsonl.partial-final" ]]; then
  echo "FAIL: expected malformed trailing fragment to be preserved as .partial-final" >&2
  exit 1
fi

count_katana="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://127.0.0.1:8000/' AND source = 'katana';")"
if [[ "$count_katana" != "1" ]]; then
  echo "FAIL: expected exactly one katana case from the valid row, got $count_katana" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana_ingest trims malformed final output fragments and preserves them separately"
