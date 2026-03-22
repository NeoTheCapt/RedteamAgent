#!/usr/bin/env bash

# resolve_engagement_dir <repo_root_or_agent_root>
# Resolution order:
# 1. ENGAGEMENT_DIR env var if it points to a real directory
# 2. engagements/.active if present
# 3. most recent engagements/* directory
resolve_engagement_dir() {
    local root="${1:-$(pwd)}"
    local engagements_dir="$root/engagements"

    if [[ -n "${ENGAGEMENT_DIR:-}" && -d "${ENGAGEMENT_DIR:-}" ]]; then
        printf '%s\n' "$ENGAGEMENT_DIR"
        return 0
    fi

    if [[ -f "$engagements_dir/.active" ]]; then
        local active
        active="$(cat "$engagements_dir/.active" 2>/dev/null || true)"
        if [[ -n "$active" && -d "$active" ]]; then
            printf '%s\n' "$active"
            return 0
        fi
    fi

    ls -td "$engagements_dir"/*/ 2>/dev/null | head -1 | sed 's|/$||'
}

set_active_engagement() {
    local root="${1:-$(pwd)}"
    local engagement_dir="${2:?engagement_dir required}"
    mkdir -p "$root/engagements"
    printf '%s\n' "$engagement_dir" > "$root/engagements/.active"
}
