#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agent"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >> "${FAKE_CURL_LOG:?}"
EOF
chmod +x "$FAKE_BIN/curl"

cat > "$FAKE_BIN/jq" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/jq "$@"
EOF
chmod +x "$FAKE_BIN/jq"

assert_contains() {
    local haystack="$1" needle="$2" msg="$3"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "[FAIL] $msg" >&2
        echo "Missing: $needle" >&2
        exit 1
    fi
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "[FAIL] $msg" >&2
        echo "Unexpected: $needle" >&2
        exit 1
    fi
}

ENG_DIR="$TMP_DIR/engagements/2026-03-23-120000-example-com"
mkdir -p "$ENG_DIR/tools"
cp "$AGENT_DIR/scripts/templates/rtcurl.sh" "$ENG_DIR/tools/rtcurl"
chmod +x "$ENG_DIR/tools/rtcurl"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "hostname": "app.example.com",
  "scope": ["app.example.com", "*.example.com"]
}
EOF

cat > "$ENG_DIR/auth.json" <<'EOF'
{
  "cookies": {
    "session": "abc123"
  },
  "headers": {
    "Authorization": "Bearer topsecret",
    "X-Test": "demo"
  }
}
EOF

export PATH="$FAKE_BIN:$PATH"
export FAKE_CURL_LOG="$TMP_DIR/curl.log"
export RTCURL_SCOPE_FILE="$ENG_DIR/scope.json"
export RTCURL_AUTH_FILE="$ENG_DIR/auth.json"
export RTCURL_USER_AGENT_FILE="$ENG_DIR/user-agent.txt"

cat > "$ENG_DIR/user-agent.txt" <<'EOF'
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36
EOF

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "Cookie: session=abc123" "in-scope request should inject cookies"
assert_contains "$ARGS" "Authorization: Bearer topsecret" "in-scope request should inject Authorization"
assert_contains "$ARGS" "X-Test: demo" "in-scope request should inject custom headers"
assert_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "in-scope request should inject engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s https://api.outside.test/resource
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_not_contains "$ARGS" "Cookie: session=abc123" "out-of-scope request must not inject cookies"
assert_not_contains "$ARGS" "Authorization: Bearer topsecret" "out-of-scope request must not inject Authorization"
assert_not_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "out-of-scope request must not inject engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s -H "Authorization: Bearer manual" https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "Authorization: Bearer manual" "explicit Authorization header should be preserved"
assert_not_contains "$ARGS" "Authorization: Bearer topsecret" "explicit Authorization header must suppress auth.json Authorization"
assert_contains "$ARGS" "Cookie: session=abc123" "explicit Authorization should not suppress cookie injection"
assert_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "explicit Authorization should not suppress engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s -b "session=manual" https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "session=manual" "explicit cookie should be preserved"
assert_not_contains "$ARGS" "Cookie: session=abc123" "explicit cookie must suppress auth.json cookies"
assert_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "explicit cookie should not suppress engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s -A "manual-agent" https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "manual-agent" "explicit -A user-agent should be preserved"
assert_not_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "explicit -A must suppress engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s -H "User-Agent: manual-header" https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "User-Agent: manual-header" "explicit User-Agent header should be preserved"
assert_not_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "explicit User-Agent header must suppress engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s -L https://app.example.com/redirect
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_not_contains "$ARGS" "Cookie: session=abc123" "location requests should not auto-inject cookies"
assert_not_contains "$ARGS" "Authorization: Bearer topsecret" "location requests should not auto-inject headers"
assert_not_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "location requests should not auto-inject engagement user-agent"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s --url https://app.example.com/account
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$ARGS" "--url" "wrapper must preserve --url syntax"
assert_contains "$ARGS" "Authorization: Bearer topsecret" "wrapper should parse --url targets for scope matching"
assert_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "wrapper should inject engagement user-agent for --url targets"

: > "$FAKE_CURL_LOG"
"$ENG_DIR/tools/rtcurl" -s https://app.example.com/account https://api.outside.test/other
ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_not_contains "$ARGS" "Authorization: Bearer topsecret" "mixed-scope multi-url requests must not inject auth"
assert_not_contains "$ARGS" "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.76 Safari/537.36" "mixed-scope multi-url requests must not inject engagement user-agent"

echo "[OK] rtcurl contracts hold"
