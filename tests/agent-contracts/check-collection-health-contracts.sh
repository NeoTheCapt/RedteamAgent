#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/agent/scripts/check_collection_health.sh"
KATANA_SCRIPT="$ROOT/agent/scripts/check_katana_usage.sh"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

eng_dir="$tmp_dir/engagement"
mkdir -p "$eng_dir/scans" "$eng_dir/pids"
cat > "$eng_dir/log.md" <<'EOF'
# Engagement Log
EOF

bash "$SCRIPT" "$eng_dir" >/dev/null

touch "$eng_dir/scans/katana_ingest.log"
if bash "$SCRIPT" "$eng_dir" >/dev/null 2>&1; then
  echo "[FAIL] collection health passed with empty katana output" >&2
  exit 1
fi

printf '{"url":"https://example.test/"}\n' > "$eng_dir/scans/katana_output.jsonl"
bash "$SCRIPT" "$eng_dir" >/dev/null

printf '{"request":{"endpoint":"https://example.test/"},"error":"hybrid: response is nil"}\n' > "$eng_dir/scans/katana_output.jsonl"
bash "$SCRIPT" "$eng_dir" >/dev/null

printf '{"request":{"endpoint":"https://example.test/"},"error":"dial tcp 127.0.0.1:443: connect: connection refused"}\n' > "$eng_dir/scans/katana_output.jsonl"
if bash "$SCRIPT" "$eng_dir" >/dev/null 2>&1; then
  echo "[FAIL] collection health passed with only non-recoverable katana error rows" >&2
  exit 1
fi

cat >> "$eng_dir/log.md" <<'EOF'
**Warning**: Raw katana launch bypassed `start_katana`/`katana_ingest.sh`; use the supported wrappers only.
EOF

if bash "$KATANA_SCRIPT" "$eng_dir" >/dev/null 2>&1; then
  echo "[FAIL] katana usage check passed with raw katana warning" >&2
  exit 1
fi

echo "collection health contracts: ok"
