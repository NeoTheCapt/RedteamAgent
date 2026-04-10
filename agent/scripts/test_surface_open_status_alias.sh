#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"
: > "$ENG_DIR/surfaces.jsonl"

"$ROOT/agent/scripts/append_surface.sh" \
  "$ENG_DIR" \
  auth_entry \
  "/rest/user/login" \
  "test-suite" \
  "open status should canonicalize to discovered" \
  "scans/surface-open.json" \
  open

cat > "$TMP_DIR/surfaces.jsonl" <<'EOF'
{"surface_type":"workflow_token","target":"/rest/2fa/status","source":"test-suite","rationale":"jsonl open status should canonicalize to discovered","evidence_ref":"scans/surface-open-jsonl.json","status":"open"}
EOF

"$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR" < "$TMP_DIR/surfaces.jsonl"

python3 - <<'PY' "$ENG_DIR/surfaces.jsonl"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]
assert len(rows) == 2, rows
for row in rows:
    assert row["status"] == "discovered", row
print("PASS: open surface status canonicalizes to discovered")
PY
