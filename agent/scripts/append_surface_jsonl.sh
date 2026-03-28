#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: append_surface_jsonl.sh <engagement_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPEND_SURFACE="$SCRIPT_DIR/append_surface.sh"

if [[ ! -x "$APPEND_SURFACE" ]]; then
    echo "ERROR: append_surface.sh not found or not executable" >&2
    exit 1
fi

while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    surface_type=$(printf '%s' "$line" | jq -r '.surface_type // empty' 2>/dev/null || true)
    target=$(printf '%s' "$line" | jq -r '.target // empty' 2>/dev/null || true)
    source_name=$(printf '%s' "$line" | jq -r '.source // empty' 2>/dev/null || true)
    rationale=$(printf '%s' "$line" | jq -r '.rationale // empty' 2>/dev/null || true)
    evidence_ref=$(printf '%s' "$line" | jq -r '.evidence_ref // ""' 2>/dev/null || true)
    status=$(printf '%s' "$line" | jq -r '.status // "discovered"' 2>/dev/null || true)

    if [[ -z "$surface_type" || -z "$target" || -z "$source_name" || -z "$rationale" ]]; then
        echo "WARN: skipping invalid surface JSONL line" >&2
        continue
    fi

    "$APPEND_SURFACE" "$ENG_DIR" "$surface_type" "$target" "$source_name" "$rationale" "$evidence_ref" "$status"
done
