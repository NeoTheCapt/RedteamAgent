#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/findings.sh"

ENG_DIR="${1:?usage: allocate_finding_id.sh <engagement_dir> <agent-name>}"
AGENT_NAME="${2:?usage: allocate_finding_id.sh <engagement_dir> <agent-name>}"

if [[ ! -f "$ENG_DIR/findings.md" ]]; then
    echo "findings.md not found in $ENG_DIR" >&2
    exit 1
fi

next_finding_id "$ENG_DIR" "$AGENT_NAME"
