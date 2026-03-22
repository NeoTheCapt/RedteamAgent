#!/usr/bin/env bash
set -euo pipefail

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/engagements/2026-03-23-120000-one" "$TMP_DIR/engagements/2026-03-23-130000-two"
printf '%s\n' "$TMP_DIR/engagements/2026-03-23-120000-one" > "$TMP_DIR/engagements/.active"

# shellcheck source=/dev/null
source "$PWD/agent/scripts/lib/engagement.sh"

resolved="$(resolve_engagement_dir "$TMP_DIR")"
if [[ "$resolved" != "$TMP_DIR/engagements/2026-03-23-120000-one" ]]; then
  echo "[FAIL] expected .active engagement to win over latest directory" >&2
  echo "resolved=$resolved" >&2
  exit 1
fi

rm -f "$TMP_DIR/engagements/.active"
resolved="$(resolve_engagement_dir "$TMP_DIR")"
if [[ "$resolved" != "$TMP_DIR/engagements/2026-03-23-130000-two" ]]; then
  echo "[FAIL] expected fallback to latest engagement when .active is absent" >&2
  echo "resolved=$resolved" >&2
  exit 1
fi

echo "[OK] Engagement selection contracts hold"
