#!/usr/bin/env bash

intel_secret_file() {
    local eng_dir="${1:?engagement dir required}"
    printf '%s\n' "$eng_dir/intel-secrets.json"
}

ensure_intel_secret_store() {
    local eng_dir="${1:?engagement dir required}"
    local path
    path="$(intel_secret_file "$eng_dir")"
    if [[ ! -s "$path" ]]; then
        printf '[]\n' >"$path"
    fi
}

truncate_secret_preview() {
    local value="${1:-}"
    if [[ ${#value} -le 20 ]]; then
        printf '%s\n' "$value"
    else
        printf '%s...\n' "${value:0:20}"
    fi
}

upsert_intel_secret() {
    local eng_dir="${1:?engagement dir required}"
    local ref="${2:?ref required}"
    local type="${3:?type required}"
    local value="${4:-}"
    local source="${5:-}"
    local notes="${6:-}"
    local path tmp

    ensure_intel_secret_store "$eng_dir"
    path="$(intel_secret_file "$eng_dir")"
    tmp="$(mktemp "${TMPDIR:-/tmp}/intel-secrets.XXXXXX")"

    python3 - <<'PY' "$path" "$tmp" "$ref" "$type" "$value" "$source" "$notes"
import json,sys
path,tmp,ref,typ,val,source,notes=sys.argv[1:]
rows=json.load(open(path))
updated=False
for row in rows:
    if row.get("ref")==ref:
        row.update({"type": typ, "value": val, "source": source, "notes": notes})
        updated=True
        break
if not updated:
    rows.append({"ref": ref, "type": typ, "value": val, "source": source, "notes": notes})
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(rows, fh, indent=2)
    fh.write("\n")
PY

    mv "$tmp" "$path"
}
