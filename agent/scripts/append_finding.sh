#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/findings.sh"

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

{
    printf '\n'
    cat "$tmp_file"
    printf '\n'
} >>"$FINDINGS_FILE"

update_finding_count "$FINDINGS_FILE"

rm -f "$tmp_file"
printf '%s\n' "$finding_id"
