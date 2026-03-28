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
  "start_time": "2026-03-28T00:00:00Z",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys

payload = {
    "timestamp": "2026-03-28T00:00:00Z",
    "request": {
        "method": "GET",
        "endpoint": "http://host.docker.internal:8000"
    },
    "response": {
        "status_code": 200,
        "headers": {
            "Content-Type": "text/html; charset=UTF-8"
        },
        "xhr_requests": [
            {
                "method": "GET",
                "endpoint": "http://host.docker.internal:8000/rest/admin/application-version",
                "headers": {
                    "Accept": "application/json"
                }
            },
            {
                "method": "POST",
                "endpoint": "http://host.docker.internal:8000/socket.io/?EIO=4&transport=polling&t=abc",
                "headers": {
                    "Content-Type": "text/plain;charset=UTF-8"
                }
            }
        ]
    }
}

# Intentionally omit trailing newline to mimic Katana's observed output.
Path(sys.argv[1]).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
PY

KATANA_INGEST_SKIP_START=1 KATANA_INGEST_ONESHOT=1 "$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null

total_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$total_cases" -ge 3 ]] || {
  echo "expected katana replay to ingest top-level + xhr requests, got $total_cases cases" >&2
  exit 1
}

sqlite3 "$ENG_DIR/cases.db" 'select source from cases order by source;' | grep -qx 'katana'
sqlite3 "$ENG_DIR/cases.db" 'select source from cases order by source;' | grep -qx 'katana-xhr'
sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -q '/rest/admin/application-version'
sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -q '/socket.io/'
root_path="$(sqlite3 "$ENG_DIR/cases.db" "select url_path from cases where source='katana' order by id limit 1;")"
[[ "$root_path" == "/" ]] || {
  echo "expected top-level katana request to normalize to /, got: $root_path" >&2
  exit 1
}

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys

payload = {
    "timestamp": "2026-03-28T00:01:00Z",
    "request": {
        "method": "GET",
        "endpoint": "http://host.docker.internal:8000/recoverable"
    },
    "error": "hybrid: response is nil"
}
Path(sys.argv[1]).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
PY
sqlite3 "$ENG_DIR/cases.db" 'delete from cases;'
KATANA_INGEST_SKIP_START=1 KATANA_INGEST_ONESHOT=1 "$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null
recoverable_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$recoverable_cases" -ge 1 ]] || {
  echo "expected recoverable katana error rows to be ingested, got $recoverable_cases cases" >&2
  exit 1
}
sqlite3 "$ENG_DIR/cases.db" 'select url from cases;' | grep -q '/recoverable'

echo "katana ingest replay contracts: ok"
