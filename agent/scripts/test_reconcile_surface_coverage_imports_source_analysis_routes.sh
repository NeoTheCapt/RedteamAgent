#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

SCRIPT="$ROOT/agent/scripts/reconcile_surface_coverage.sh"
SCHEMA="$ROOT/agent/scripts/schema.sql"
ENG_DIR="$TMP_DIR/eng"

mkdir -p "$ENG_DIR/scans/source-analysis"
cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:3000",
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
: > "$ENG_DIR/surfaces.jsonl"
sqlite3 "$ENG_DIR/cases.db" < "$SCHEMA"

cat > "$ENG_DIR/scans/source-analysis/page-batch-001-summary.json" <<'EOF'
{
  "routes": [
    "search",
    "track-result",
    "wallet",
    "**",
    "address/edit/:addressId",
    "/#/score-board"
  ]
}
EOF

"$SCRIPT" "$ENG_DIR" --ingest-followups >/dev/null

python3 - <<'PY' "$ENG_DIR"
import sqlite3, sys
from pathlib import Path
eng = Path(sys.argv[1])
db = sqlite3.connect(eng / 'cases.db')
rows = db.execute("select method, url, url_path, type, source, status from cases where source='operator-surface-coverage' order by id").fetchall()
db.close()
assert ('GET', 'http://127.0.0.1:3000/#search', '/#search', 'page', 'operator-surface-coverage', 'pending') in rows, rows
assert ('GET', 'http://127.0.0.1:3000/#track-result', '/#track-result', 'page', 'operator-surface-coverage', 'pending') in rows, rows
assert ('GET', 'http://127.0.0.1:3000/#wallet', '/#wallet', 'page', 'operator-surface-coverage', 'pending') in rows, rows
assert ('GET', 'http://127.0.0.1:3000/#score-board', '/#score-board', 'page', 'operator-surface-coverage', 'pending') in rows, rows
assert not any('/#**' in row[1] for row in rows), rows
assert not any('address/edit' in row[1] for row in rows), rows
PY

echo "PASS: reconcile_surface_coverage ingests concrete source-analysis SPA routes as page follow-ups"
