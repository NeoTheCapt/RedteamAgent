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
robots_wildcard_noise_request='{"url":"https://example.test/*/kyc-verify$","source_ref":"https://example.test/robots.txt","tag":"file","attribute":"robotstxt","error":"hybrid: response is nil"}'
binary_source_noise_request='{"url":"https://example.test/assets/public/images/w","source_ref":"https://example.test/assets/public/images/JuiceShop_Logo.png","tag":"html","attribute":"regex","error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}'
wasm_source_noise_request='{"url":"https://example.test/cdn/assets/okfe/okt/polyfill-automatic/Bun/","source_ref":"https://example.test/cdn/assets/okfe/okt/polyfill-automatic/f220424697ac3c8ba96a.wasm.br","tag":"html","attribute":"regex","error":"hybrid: response is nil"}'
stacktrace_internal_regex_request='{"url":"http://127.0.0.1:8000/juice-shop/node_modules/express/lib/router/index.js","source_ref":"http://127.0.0.1:8000/redirect?to=https","tag":"html","attribute":"regex","error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}'
stacktrace_internal_source_request='{"url":"http://127.0.0.1:8000/juice-shop/node_modules/express/lib/router/styles.css","source_ref":"http://127.0.0.1:8000/juice-shop/node_modules/express/lib/router/index.js","tag":"link","attribute":"href","error":"cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""}'

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

if katana_request_should_ingest "$robots_wildcard_noise_request"; then
  echo "[FAIL] robots wildcard noise path should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$binary_source_noise_request"; then
  echo "[FAIL] katana discovery from binary source should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$wasm_source_noise_request"; then
  echo "[FAIL] katana discovery from wasm source should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$stacktrace_internal_regex_request"; then
  echo "[FAIL] stack-trace regex discovery of internal source path should not be ingested" >&2
  exit 1
fi

if katana_request_should_ingest "$stacktrace_internal_source_request"; then
  echo "[FAIL] follow-on discovery from internal stack-trace source path should not be ingested" >&2
  exit 1
fi

echo "katana ingest contracts: ok"
