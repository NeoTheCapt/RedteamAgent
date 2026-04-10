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
cat > "$output" <<'JSON'
{"request":{"method":"GET","endpoint":"http://host.docker.internal:8000/"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"},"xhr_requests":[{"method":"GET","endpoint":"http://host.docker.internal:8000/rest/admin/application-version","headers":{"Authorization":"Bearer secret-jwt","Cookie":"sid=secret-cookie","Accept":"application/json"}}]}}
JSON
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
row = rows[0]
assert row["request"]["endpoint"] == "http://127.0.0.1:8000/"
xhr = row["response"]["xhr_requests"][0]
assert xhr["endpoint"] == "http://127.0.0.1:8000/rest/admin/application-version"
assert xhr["headers"]["Authorization"] == "<redacted>"
assert xhr["headers"]["Cookie"] == "<redacted>"
assert xhr["headers"]["Accept"] == "application/json"
text = path.read_text()
assert "secret-jwt" not in text
assert "secret-cookie" not in text
assert "host.docker.internal" not in text
assert "<redacted>" in text
PY

if [[ -e "$ENG_DIR/scans/.katana_output.raw.jsonl" ]]; then
  echo "FAIL: raw katana sidecar should be removed after ingest exits" >&2
  exit 1
fi

echo "PASS: katana ingest redacts live headers and rewrites loopback aliases in the public artifact"
