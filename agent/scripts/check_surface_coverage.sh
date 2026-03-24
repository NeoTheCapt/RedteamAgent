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
blocked_deferred=[]
strict_deferred_types={
    "account_recovery",
    "dynamic_render",
    "object_reference",
    "privileged_write",
}
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line=line.strip()
        if not line:
            continue
        row=json.loads(line)
        surface_type=row.get("surface_type")
        target=row.get("target")
        status=row.get("status")
        if status == "discovered":
            unresolved.append(f'{surface_type} | {target}')
        elif status == "deferred" and surface_type in strict_deferred_types:
            blocked_deferred.append(f'{surface_type} | {target}')
if unresolved or blocked_deferred:
    if unresolved:
        print("Uncovered surfaces remain:")
        for item in unresolved:
            print(f"  - {item}")
    if blocked_deferred:
        print("High-risk surfaces cannot remain deferred:")
        for item in blocked_deferred:
            print(f"  - {item}")
        print("Resolve them as covered or not_applicable before finishing Test/Report.")
    for item in unresolved:
        pass
    sys.exit(1)
print("surface coverage: ok")
PY
)" || {
    printf '%s\n' "$out" >&2
    exit 1
}

printf '%s\n' "$out"
