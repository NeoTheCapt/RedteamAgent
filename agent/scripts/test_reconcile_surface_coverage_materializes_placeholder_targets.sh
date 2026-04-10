#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

SCRIPT="$ROOT/agent/scripts/reconcile_surface_coverage.sh"
SCHEMA="$ROOT/agent/scripts/schema.sql"
ENG_DIR="$TMP_DIR/eng"

mkdir -p "$ENG_DIR/scans"
cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "scope": ["127.0.0.1", "localhost", "host.docker.internal"],
  "status": "in_progress",
  "current_phase": "consume_test"
}
EOF
cat > "$ENG_DIR/findings.md" <<'EOF'
# Findings
EOF
cat > "$ENG_DIR/auth.json" <<'EOF'
{}
EOF
cat > "$ENG_DIR/surfaces.jsonl" <<'EOF'
{"surface_type":"object_reference","target":"GET /rest/track-order/...","source":"source-analyzer","rationale":"generic order lookup route","evidence_ref":"scans/source-analysis/page-batch-001-summary.json","status":"discovered"}
{"surface_type":"object_reference","target":"GET /api/Products/{id}","source":"source-analyzer","rationale":"JS-discovered REST resource route","evidence_ref":"scans/source-analysis/page-batch-001-summary.json","status":"discovered"}
EOF
sqlite3 "$ENG_DIR/cases.db" < "$SCHEMA"

"$SCRIPT" "$ENG_DIR" --ingest-followups >/dev/null

python3 - <<'PY' "$ENG_DIR"
import sqlite3, sys
from pathlib import Path
eng = Path(sys.argv[1])
db = sqlite3.connect(eng / 'cases.db')
rows = db.execute("select method, url, url_path, type, source, status from cases where source='operator-surface-coverage' order by id").fetchall()
db.close()
assert ('GET', 'http://127.0.0.1:8000/rest/track-order/1', '/rest/track-order/1', 'api', 'operator-surface-coverage', 'pending') in rows, rows
assert ('GET', 'http://127.0.0.1:8000/api/Products/1', '/api/Products/1', 'api', 'operator-surface-coverage', 'pending') in rows, rows
assert not any(row[2] == '/rest/track-order/...' for row in rows), rows
assert not any(row[2] == '/api/Products/{id}' for row in rows), rows
PY

echo "PASS: reconcile_surface_coverage materializes placeholder targets into concrete follow-up cases"
