#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/surfaces.sh"

ENG_DIR="${1:?usage: check_surface_coverage.sh <engagement_dir>}"
SURFACE_FILE="$(surface_file_path "$ENG_DIR")"

[[ -f "$SURFACE_FILE" ]] || { echo "surfaces.jsonl not found in $ENG_DIR" >&2; exit 1; }

out="$(python3 - <<'PY' "$SURFACE_FILE"
import json,sys
path=sys.argv[1]
unresolved=[]
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line=line.strip()
        if not line:
            continue
        row=json.loads(line)
        if row.get("status") == "discovered":
            unresolved.append(f'{row.get("surface_type")} | {row.get("target")}')
if unresolved:
    print("Uncovered surfaces remain:")
    for item in unresolved:
        print(f"  - {item}")
    sys.exit(1)
print("surface coverage: ok")
PY
)" || {
    printf '%s\n' "$out" >&2
    exit 1
}

printf '%s\n' "$out"
