#!/usr/bin/env bash
# Pre-commit dispatcher: runs every block-*.sh hook in agent/scripts/hooks/.
# Install once: cp agent/scripts/hooks/pre-commit-dispatcher.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# Adding a new check is just dropping `block-<name>.sh` next to this file.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
HOOK_DIR="${REPO_ROOT}/agent/scripts/hooks"

[[ -d "$HOOK_DIR" ]] || { echo "pre-commit: hooks dir missing: $HOOK_DIR"; exit 0; }

failed=0
for hook in "$HOOK_DIR"/block-*.sh; do
    [[ -x "$hook" ]] || continue
    if ! bash "$hook"; then
        failed=1
    fi
done

exit "$failed"
