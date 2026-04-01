#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/surface-aliases.XXXXXX")"
ENG_DIR="$TMP_DIR/engagement"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$ENG_DIR"
touch "$ENG_DIR/surfaces.jsonl"

"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "auth_surface" "/auth/login" "test" "alias auth surface" "evidence" "deferred"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "update_distribution" "/downloads/appcast.xml" "test" "alias update surface" "evidence" "covered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "cors_surface" "/public/data" "test" "alias cors surface" "evidence" "discovered"

cat >"$TMP_DIR/aliases.jsonl" <<'EOF'
{"surface_type":"auth_surface","target":"/auth/sso","source":"jsonl","rationale":"alias auth jsonl","status":"deferred"}
{"surface_type":"update_distribution","target":"/downloads/manifest.json","source":"jsonl","rationale":"alias update jsonl","status":"covered"}
{"surface_type":"cors_surface","target":"/public/json","source":"jsonl","rationale":"alias cors jsonl","status":"discovered"}
EOF
"$REPO_ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR" <"$TMP_DIR/aliases.jsonl"

python3 - <<'PY' "$ENG_DIR/surfaces.jsonl"
import json
import sys
from collections import Counter

path = sys.argv[1]
rows = [json.loads(line) for line in open(path, 'r', encoding='utf-8') if line.strip()]
counts = Counter(row['surface_type'] for row in rows)
assert counts['auth_entry'] == 2, counts
assert counts['file_handling'] == 2, counts
assert counts['cors_review'] == 2, counts
assert 'auth_surface' not in counts, counts
assert 'update_distribution' not in counts, counts
assert 'cors_surface' not in counts, counts
print('surface alias canonicalization OK')
PY
