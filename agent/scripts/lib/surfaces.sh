#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/placeholders.sh"
source "$SCRIPT_DIR/loopback_scope.sh"

surface_file_path() {
    local eng_dir="${1:?engagement dir required}"
    printf '%s\n' "$eng_dir/surfaces.jsonl"
}

surface_canonical_type() {
    local surface_type="${1:?surface type required}"
    surface_type="$(printf '%s' "$surface_type" | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
    case "$surface_type" in
        spa_route|spa|client_route|client_side_route|frontend_route)
            printf '%s\n' "dynamic_render"
            ;;
        *)
            printf '%s\n' "$surface_type"
            ;;
    esac
}

surface_validate_type() {
    local surface_type="${1:?surface type required}"
    surface_type="$(surface_canonical_type "$surface_type")"
    case "$surface_type" in
        auth_entry|account_recovery|object_reference|privileged_write|file_handling|dynamic_render|api_documentation|workflow_token)
            return 0
            ;;
        *)
            echo "invalid surface_type: $surface_type" >&2
            return 1
            ;;
    esac
}

surface_validate_status() {
    local status="${1:?status required}"
    case "$status" in
        discovered|covered|not_applicable|deferred)
            return 0
            ;;
        *)
            echo "invalid surface status: $status" >&2
            return 1
            ;;
    esac
}

surface_validate_target() {
    local target="${1:?target required}"
    if contains_surface_placeholder "$target"; then
        echo "invalid surface target placeholder: $target" >&2
        return 1
    fi
}

ensure_surface_file() {
    local eng_dir="${1:?engagement dir required}"
    local surface_file
    surface_file="$(surface_file_path "$eng_dir")"
    mkdir -p "$eng_dir"
    touch "$surface_file"
}

upsert_surface_record() {
    local eng_dir="${1:?engagement dir required}"
    local surface_type="${2:?surface type required}"
    surface_type="$(surface_canonical_type "$surface_type")"
    local target="${3:?target required}"
    local source="${4:?source required}"
    local rationale="${5:-}"
    local evidence_ref="${6:-}"
    local status="${7:-discovered}"
    local surface_file tmp_file

    surface_validate_type "$surface_type"
    surface_validate_status "$status"
    surface_validate_target "$target"

    local normalized_target
    normalized_target="$(normalize_target_for_scope "$eng_dir" "$target")" || {
        if [[ $? -eq 10 ]]; then
            return 0
        fi
        return 1
    }
    target="$normalized_target"

    ensure_surface_file "$eng_dir"
    surface_file="$(surface_file_path "$eng_dir")"
    tmp_file="$(mktemp "${TMPDIR:-/tmp}/surfaces-jsonl.XXXXXX")"

    python3 - <<'PY' "$surface_file" "$tmp_file" "$surface_type" "$target" "$source" "$rationale" "$evidence_ref" "$status"
import json,sys

surface_file, tmp_file, surface_type, target, source, rationale, evidence_ref, status = sys.argv[1:]
rows = []
seen = False

with open(surface_file, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("surface_type") == surface_type and row.get("target") == target:
            row["source"] = source
            row["rationale"] = rationale
            row["evidence_ref"] = evidence_ref
            row["status"] = status
            seen = True
        rows.append(row)

if not seen:
    rows.append({
        "surface_type": surface_type,
        "target": target,
        "source": source,
        "rationale": rationale,
        "evidence_ref": evidence_ref,
        "status": status,
    })

with open(tmp_file, "w", encoding="utf-8") as out:
    for row in rows:
        out.write(json.dumps(row, ensure_ascii=True) + "\n")
PY

    mv "$tmp_file" "$surface_file"
}
