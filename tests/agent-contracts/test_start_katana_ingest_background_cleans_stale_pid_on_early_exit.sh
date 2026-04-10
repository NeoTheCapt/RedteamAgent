#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

HARNESS_ROOT="$TMP_DIR/harness"
mkdir -p "$HARNESS_ROOT/scripts/lib"

ln -s "$ROOT/agent/scripts/start_katana_ingest_background.sh" "$HARNESS_ROOT/scripts/start_katana_ingest_background.sh"
ln -s "$ROOT/agent/scripts/lib/processes.sh" "$HARNESS_ROOT/scripts/lib/processes.sh"

cat > "$HARNESS_ROOT/scripts/katana_ingest.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 1
EOF
chmod +x "$HARNESS_ROOT/scripts/katana_ingest.sh"

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

set +e
output="$(cd "$HARNESS_ROOT" && ./scripts/start_katana_ingest_background.sh "$ENG_DIR" 2>&1)"
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "FAIL: expected background launcher to fail when katana_ingest exits immediately" >&2
  echo "$output" >&2
  exit 1
fi

if [[ -f "$ENG_DIR/pids/katana_ingest.pid" ]]; then
  echo "FAIL: expected no stale katana_ingest.pid after early exit" >&2
  cat "$ENG_DIR/pids/katana_ingest.pid" >&2 || true
  exit 1
fi

if [[ "$output" != *"exited before background registration completed"* ]]; then
  echo "FAIL: expected early-exit error message, got:" >&2
  echo "$output" >&2
  exit 1
fi

echo "PASS: background katana launcher removes stale pid files when katana_ingest dies immediately"
