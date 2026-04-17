#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/findings.sh"
EMIT_RUNTIME_EVENT="$SCRIPT_DIR/emit_runtime_event.sh"

ENG_DIR="${1:?usage: append_finding.sh <engagement_dir> <agent-name> <finding-body-file>}"
AGENT_NAME="${2:?usage: append_finding.sh <engagement_dir> <agent-name> <finding-body-file>}"
BODY_FILE="${3:?usage: append_finding.sh <engagement_dir> <agent-name> <finding-body-file>}"
FINDINGS_FILE="$ENG_DIR/findings.md"

[[ -f "$FINDINGS_FILE" ]] || { echo "findings.md not found in $ENG_DIR" >&2; exit 1; }
[[ -f "$BODY_FILE" ]] || { echo "finding body file not found: $BODY_FILE" >&2; exit 1; }

lock_dir="$(acquire_finding_lock "$ENG_DIR")"
trap 'release_finding_lock "$lock_dir"' EXIT

finding_id="$(next_finding_id "$ENG_DIR" "$AGENT_NAME")"
tmp_file="$(mktemp "${TMPDIR:-/tmp}/finding-append.XXXXXX")"

if ! replace_finding_placeholder "$BODY_FILE" "$finding_id" "$tmp_file"; then
    rm -f "$tmp_file"
    echo "finding body must contain a heading with [FINDING-ID] placeholder or existing finding id" >&2
    exit 1
fi

candidate_title="$(extract_finding_title "$tmp_file")"
existing_id="$(find_existing_finding_id "$FINDINGS_FILE" "$tmp_file")"
if [[ -n "$existing_id" ]]; then
    rm -f "$tmp_file"
    if [[ -n "$candidate_title" ]]; then
        printf 'duplicate finding already present as %s: %s\n' "$existing_id" "$candidate_title" >&2
    else
        printf 'duplicate finding already present as %s\n' "$existing_id" >&2
    fi
    printf '%s\n' "$existing_id"
    exit 0
fi

{
    printf '\n'
    cat "$tmp_file"
    printf '\n'
} >>"$FINDINGS_FILE"

update_finding_count "$FINDINGS_FILE"

rm -f "$tmp_file"
if [[ -f "$EMIT_RUNTIME_EVENT" ]]; then
    # Best-effort extraction: severity/category are optional.
    # Parse from body lines like "**Severity**: critical" / "**Category**: injection".
    severity="$(grep -oE '^\*\*Severity\*\*:[[:space:]]*[A-Za-z]+' "$BODY_FILE" 2>/dev/null \
                | sed 's/^.*:[[:space:]]*//' | tr 'A-Z' 'a-z' || true)"
    category="$(grep -oE '^\*\*Category\*\*:[[:space:]]*[A-Za-z0-9-]+' "$BODY_FILE" 2>/dev/null \
                | sed 's/^.*:[[:space:]]*//' | tr 'A-Z' 'a-z' || true)"
    payload="$(jq -cn \
        --arg finding_id "$finding_id" \
        --arg severity "${severity:-}" \
        --arg category "${category:-}" \
        --arg title "${candidate_title:-}" \
        '{finding_id:$finding_id, severity:$severity, category:$category, title:$title}')"
    bash "$EMIT_RUNTIME_EVENT" \
        "finding.created" \
        "${ORCHESTRATOR_PHASE:-unknown}" \
        "$finding_id" \
        "$AGENT_NAME" \
        "${candidate_title:-Added $finding_id}" \
        --kind finding \
        --payload-json "$payload"
fi
printf '%s\n' "$finding_id"
