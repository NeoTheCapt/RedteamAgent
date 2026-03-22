#!/usr/bin/env bash
# test-engage.sh — test if OpenCode /engage hangs
# Exit: 0=PASS, 1=HANG, 2=ERROR
set -uo pipefail
TIMEOUT="${1:-90}"
DIR="${2:-.}"

[ -d "$DIR" ] || { echo "ERR: $DIR not found" >&2; exit 2; }
[ -f "$DIR/.opencode/opencode.json" ] || { echo "ERR: no config in $DIR" >&2; exit 2; }

OUT=$(mktemp /tmp/oc-XXXXXX.log)
trap "rm -f $OUT" EXIT

(cd "$DIR" && rm -rf engagements/* 2>/dev/null; mkdir -p engagements && timeout "$TIMEOUT" opencode run 'run the /engage command against http://127.0.0.1:8000') > "$OUT" 2>&1

CLEAN=$(sed 's/\x1b\[[0-9;]*m//g' "$OUT")

if echo "$CLEAN" | grep -qiE "Authentication|Phase 1|Phase.*Recon|Approve|dispatch|Reply \(1-"; then
  echo "PASS"
  exit 0
elif echo "$CLEAN" | grep -qiE "Configuration is invalid|bad file reference"; then
  echo "ERROR"
  exit 2
else
  echo "HANG ($(wc -l < "$OUT" | tr -d ' ') lines)"
  echo "$CLEAN" | grep -E '^\$|^✱|^→' | tail -2
  exit 1
fi
