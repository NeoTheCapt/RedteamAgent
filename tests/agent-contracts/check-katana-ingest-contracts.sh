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
good_request='{"url":"https://example.test/rest/admin/application-configuration","source_ref":"https://example.test/"}'
quoted_noise_request='{"url":"https://example.test/rest/admin/%5C%22/"}'
binary_source_noise_request='{"url":"https://example.test/assets/public/images/w","source_ref":"https://example.test/assets/public/images/JuiceShop_Logo.png","tag":"html","attribute":"regex","error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}'

katana_line_should_ingest "$good"
katana_line_should_ingest "$plain"
katana_line_should_ingest "$recoverable"
katana_request_should_ingest "$good_request"

if katana_line_should_ingest "$hard_error"; then
  echo "[FAIL] non-recoverable katana error line should not be ingested" >&2
  exit 1
fi

if katana_line_should_ingest "$empty"; then
  echo "[FAIL] katana line without URL should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$quoted_noise_request"; then
  echo "[FAIL] encoded quote/backslash katana path should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$binary_source_noise_request"; then
  echo "[FAIL] katana discovery from binary source should not be ingested" >&2
  exit 1
fi

echo "katana ingest contracts: ok"
