#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'pkill -f "$TMP_DIR/scripts/katana_ingest.sh" >/dev/null 2>&1 || true; rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/scripts/lib" "$TMP_DIR/engagement/scans" "$TMP_DIR/engagement/pids"
cp "$ROOT/agent/scripts/start_katana_ingest_background.sh" "$TMP_DIR/scripts/start_katana_ingest_background.sh"
cp "$ROOT/agent/scripts/lib/processes.sh" "$TMP_DIR/scripts/lib/processes.sh"
chmod +x "$TMP_DIR/scripts/start_katana_ingest_background.sh"

cat > "$TMP_DIR/scripts/katana_ingest.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
sleep 30
EOF
chmod +x "$TMP_DIR/scripts/katana_ingest.sh"

first_pid="$(cd "$TMP_DIR" && ./scripts/start_katana_ingest_background.sh "$TMP_DIR/engagement")"
[[ -n "$first_pid" ]] || {
  echo "expected first katana_ingest pid" >&2
  exit 1
}
kill -0 "$first_pid"

second_pid="$(cd "$TMP_DIR" && ./scripts/start_katana_ingest_background.sh "$TMP_DIR/engagement")"
[[ "$second_pid" == "$first_pid" ]] || {
  echo "expected singleton restart guard to reuse pid $first_pid, got $second_pid" >&2
  exit 1
}

kill -0 "$second_pid"

kill "$first_pid"
wait "$first_pid" 2>/dev/null || true

echo "katana singleton contracts: ok"
