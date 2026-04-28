#!/usr/bin/env bash
# Block commits that re-introduce root-level duplicates of agent runtime dirs.
# agent/ is the canonical source; see orchestrator/backend/app/config.py agent_source_dir.

set -euo pipefail

forbidden=( ".opencode" "scripts" "skills" "references" "docker" )
violations=()

for path in "${forbidden[@]}"; do
  if git diff --cached --name-only | grep -qE "^${path}/"; then
    violations+=("$path/")
  fi
done

if [ ${#violations[@]} -gt 0 ]; then
  echo "ERROR: commit introduces root-level paths that duplicate agent/ runtime:" >&2
  printf '  %s\n' "${violations[@]}" >&2
  echo "" >&2
  echo "Move these changes under agent/ instead. See: orchestrator/backend/app/config.py (agent_source_dir)" >&2
  exit 1
fi
