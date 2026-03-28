#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/agent/scripts/lib/katana.sh"

good='{"request":{"endpoint":"https://example.test/about","method":"GET"}}'
plain='https://example.test/plain'
recoverable='{"request":{"endpoint":"https://example.test/bad"},"error":"hybrid: response is nil"}'
hard_error='{"request":{"endpoint":"https://example.test/down"},"error":"dial tcp 127.0.0.1:443: connect: connection refused"}'
empty='{"foo":"bar"}'

katana_line_should_ingest "$good"
katana_line_should_ingest "$plain"
katana_line_should_ingest "$recoverable"

if katana_line_should_ingest "$hard_error"; then
  echo "[FAIL] non-recoverable katana error line should not be ingested" >&2
  exit 1
fi

if katana_line_should_ingest "$empty"; then
  echo "[FAIL] katana line without URL should not be ingested" >&2
  exit 1
fi

echo "katana ingest contracts: ok"
