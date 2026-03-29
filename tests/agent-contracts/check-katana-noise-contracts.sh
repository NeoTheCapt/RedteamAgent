#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NOISE_LIB="$ROOT_DIR/agent/scripts/lib/noise.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -f "$NOISE_LIB" ]] || fail "missing noise library: $NOISE_LIB"

# shellcheck source=/dev/null
source "$NOISE_LIB"

expect_noise() {
  local path="$1"
  if ! is_katana_noise_path "$path"; then
    fail "expected noise path: $path"
  fi
}

expect_keep() {
  local path="$1"
  if is_katana_noise_path "$path"; then
    fail "expected real path to survive: $path"
  fi
}

matches_out_of_scope() {
  local url="$1"
  local regex
  while IFS= read -r regex; do
    [[ -n "$regex" ]] || continue
    if printf '%s' "$url" | grep -Eq "$regex"; then
      return 0
    fi
  done < <(katana_emit_out_of_scope_regexes)
  return 1
}

expect_out_of_scope() {
  local url="$1"
  if ! matches_out_of_scope "$url"; then
    fail "expected out-of-scope regex to match: $url"
  fi
}

expect_keep_out_of_scope() {
  local url="$1"
  if matches_out_of_scope "$url"; then
    fail "expected out-of-scope regex to keep: $url"
  fi
}

expect_noise '/%7B%7Bhref%7D%7D'
expect_noise "/'+L(i[8])+'"
expect_noise '/application/vnd.ms-word.do'
expect_noise '/Edge/'
expect_noise '/Trident/'
expect_noise '/-'
expect_noise '/rest/admin/%5C%22/'
expect_noise '/api/%5C%22/ftp/legal.md%5C%22'
expect_noise '/%5C/index.html'
expect_noise '/*?*&src=*'
expect_noise '/*/kyc-verify$'
expect_noise '/cdn/assets/okfe/okt/polyfill-automatic/Bun/'
expect_noise '/cdn/assets/okfe/util/monitor/2.6.149/scripts/lib/'
expect_noise '/assets/public/images/'
expect_noise '/assets/public/images/chunk-24EZLZ4I.js'
expect_noise '/assets/public/images/assets/public/main.js'
expect_noise '/assets/public/assets/public/main.js'
expect_noise '/Trident/assets/public/assets/public/main.js'
expect_noise '/Trident/assets/public/assets/public/assets/public/chunk-4MIYPPGW.js'
expect_noise '/assets/i18n/assets/public/polyfills.js'

expect_keep '/rest/user/login'
expect_keep '/rest/products/42/reviews'
expect_keep '/address/create'
expect_keep '/track-result/new'

expect_out_of_scope 'https://www.okx.com/cdn/assets/okfe/util/monitor/2.6.149/scripts/lib/'
expect_out_of_scope 'https://www.okx.com/cdn/assets/okfe/okt/polyfill-automatic/Bun/'
expect_out_of_scope 'http://127.0.0.1:8000/juice-shop/node_modules/express/lib/router/index.js'
expect_out_of_scope 'http://127.0.0.1:8000/juice-shop/build/routes/assets/public/main.js'
expect_out_of_scope 'http://127.0.0.1:8000/assets/public/images/chunk-24EZLZ4I.js'
expect_out_of_scope 'http://127.0.0.1:8000/assets/public/assets/public/main.js'
expect_out_of_scope 'http://127.0.0.1:8000/Trident/assets/public/assets/public/main.js'
expect_out_of_scope 'http://127.0.0.1:8000/assets/i18n/assets/public/polyfills.js'
expect_keep_out_of_scope 'http://127.0.0.1:8000/rest/user/login'
expect_keep_out_of_scope 'https://www.okx.com/v3/users/support/common/check-country-limit'

echo "katana noise contracts: ok"
