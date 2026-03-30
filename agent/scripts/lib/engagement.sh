#!/usr/bin/env bash

canonicalize_engagement_dir() {
    local root="${1:-$(pwd)}"
    local candidate="${2:-}"

    [[ -n "$candidate" ]] || return 1

    if [[ "$candidate" != /* ]]; then
        candidate="$root/$candidate"
    fi

    [[ -d "$candidate" ]] || return 1
    (
        cd "$candidate" >/dev/null 2>&1 && pwd
    )
}

# resolve_engagement_dir <repo_root_or_agent_root>
# Resolution order:
# 1. ENGAGEMENT_DIR env var if it points to a real directory
# 2. engagements/.active if present
# 3. most recent engagements/* directory
resolve_engagement_dir() {
    local root="${1:-$(pwd)}"
    local engagements_dir="$root/engagements"
    local resolved

    if [[ -n "${ENGAGEMENT_DIR:-}" ]]; then
        resolved="$(canonicalize_engagement_dir "$root" "${ENGAGEMENT_DIR:-}" 2>/dev/null || true)"
        if [[ -n "$resolved" ]]; then
            printf '%s\n' "$resolved"
            return 0
        fi
    fi

    if [[ -f "$engagements_dir/.active" ]]; then
        local active
        active="$(cat "$engagements_dir/.active" 2>/dev/null || true)"
        resolved="$(canonicalize_engagement_dir "$root" "$active" 2>/dev/null || true)"
        if [[ -n "$resolved" ]]; then
            printf '%s\n' "$resolved"
            return 0
        fi
    fi

    ls -td "$engagements_dir"/*/ 2>/dev/null | head -1 | sed 's|/$||'
}

set_active_engagement() {
    local root="${1:-$(pwd)}"
    local engagement_dir="${2:?engagement_dir required}"
    local resolved marker

    root="$(cd "$root" >/dev/null 2>&1 && pwd)"
    resolved="$(canonicalize_engagement_dir "$root" "$engagement_dir")"
    marker="$resolved"
    if [[ "$resolved" == "$root"/engagements/* ]]; then
        marker="engagements/${resolved#"$root"/engagements/}"
    fi
    mkdir -p "$root/engagements"
    printf '%s\n' "$marker" > "$root/engagements/.active"
}
