#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"
: > "$ENG_DIR/surfaces.jsonl"

source "$ROOT/agent/scripts/lib/surfaces.sh"

canonical="$(surface_canonical_type jwt)"
if [[ "$canonical" != "workflow_token" ]]; then
  echo "FAIL: expected surface_canonical_type jwt -> workflow_token, got: $canonical" >&2
  exit 1
fi

"$ROOT/agent/scripts/append_surface.sh" \
  "$ENG_DIR" \
  jwt \
  "Bearer token validation on an actually enforced auth endpoint" \
  "test-suite" \
  "jwt alias should map into workflow_token" \
  "scans/jwt-check.json" \
  deferred

python3 - <<'PY' "$ENG_DIR/surfaces.jsonl"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]
assert len(rows) == 1, rows
row = rows[0]
assert row["surface_type"] == "workflow_token", row
assert row["status"] == "deferred", row
assert row["target"] == "Bearer token validation on an actually enforced auth endpoint", row
PY

cat > "$TMP_DIR/surfaces.jsonl" <<'EOF'
{"surface_type":"jwt","target":"JWT follow-up surface","source":"test-suite","rationale":"explicit jwt alias should be accepted","evidence_ref":"scans/jwt-followup.json","status":"deferred"}
EOF

"$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR" < "$TMP_DIR/surfaces.jsonl"

python3 - <<'PY' "$ENG_DIR/surfaces.jsonl"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]
match = [row for row in rows if row["target"] == "JWT follow-up surface"]
assert len(match) == 1, rows
assert match[0]["surface_type"] == "workflow_token", match[0]
assert match[0]["status"] == "deferred", match[0]
PY

echo "PASS: jwt surface aliases map to workflow_token for direct and JSONL surface ingestion"
