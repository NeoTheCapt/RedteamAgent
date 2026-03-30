#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/engagement-active.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$TMP_DIR/repo/engagements/2026-03-29-000000-example/tools"
printf '%s\n' 'engagements/2026-03-29-000000-example' > "$TMP_DIR/repo/engagements/.active"

resolved_from_elsewhere="$(
  cd "$TMP_DIR"
  source "$REPO_ROOT/agent/scripts/lib/engagement.sh"
  resolve_engagement_dir "$TMP_DIR/repo"
)"
expected="$(cd "$TMP_DIR/repo/engagements/2026-03-29-000000-example" && pwd)"
[[ "$resolved_from_elsewhere" == "$expected" ]]

canonical_active_dir="$TMP_DIR/repo/engagements/2026-03-29-010101-second"
mkdir -p "$canonical_active_dir"
(
  cd "$TMP_DIR/repo"
  source "$REPO_ROOT/agent/scripts/lib/engagement.sh"
  set_active_engagement "$TMP_DIR/repo" 'engagements/2026-03-29-010101-second'
)
canonical_active_dir="$(cd "$canonical_active_dir" && pwd)"
active_marker="$(cat "$TMP_DIR/repo/engagements/.active")"
[[ "$active_marker" == 'engagements/2026-03-29-010101-second' ]]

printf '%s\n' "$canonical_active_dir" > "$TMP_DIR/repo/engagements/.active"
resolved_from_absolute_marker="$(
  cd "$TMP_DIR"
  source "$REPO_ROOT/agent/scripts/lib/engagement.sh"
  resolve_engagement_dir "$TMP_DIR/repo"
)"
[[ "$resolved_from_absolute_marker" == "$canonical_active_dir" ]]

env_override_relative="$(
  cd "$TMP_DIR"
  export ENGAGEMENT_DIR='repo/engagements/2026-03-29-010101-second'
  source "$REPO_ROOT/agent/scripts/lib/engagement.sh"
  resolve_engagement_dir "$TMP_DIR"
)"
[[ "$env_override_relative" == "$canonical_active_dir" ]]

echo "engagement active resolution OK"
