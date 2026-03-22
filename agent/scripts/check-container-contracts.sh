#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >> "${FAKE_DOCKER_LOG:?}"
if [[ "${1:-}" == "ps" || "${1:-}" == "image" || "${1:-}" == "info" ]]; then
  exit 0
fi
exit 0
EOF
chmod +x "$FAKE_BIN/docker"

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

ENG1="$TMP_DIR/engagements/2026-03-23-120000-example-com"
ENG2="$TMP_DIR/engagements/2026-03-23-120500-admin-example-com"
mkdir -p "$ENG1/scans" "$ENG2/scans"

cat > "$ENG1/auth.json" <<'EOF'
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
export FAKE_DOCKER_LOG="$TMP_DIR/docker.log"

# shellcheck source=/dev/null
source "$ROOT_DIR/scripts/lib/container.sh"

export ENGAGEMENT_DIR="$ENG1"
start_katana "https://target.local"
KATANA_ARGS="$(tr '\n' ' ' < "$FAKE_DOCKER_LOG")"

assert_not_contains "$KATANA_ARGS" "--name redteam-katana " "Katana container name should not be global"
assert_contains "$KATANA_ARGS" "--name redteam-katana-2026-03-23-120000-example-com" "Katana container name should include engagement slug"
assert_contains "$KATANA_ARGS" "Cookie: session=abc123" "Katana should receive cookies from auth.json"
assert_contains "$KATANA_ARGS" "Authorization: Bearer topsecret" "Katana should receive Authorization header from auth.json"
assert_contains "$KATANA_ARGS" "X-Test: demo" "Katana should receive arbitrary custom headers from auth.json"

: > "$FAKE_DOCKER_LOG"
export ENGAGEMENT_DIR="$ENG2"
start_proxy
PROXY_ARGS="$(tr '\n' ' ' < "$FAKE_DOCKER_LOG")"

assert_not_contains "$PROXY_ARGS" "--name redteam-proxy " "Proxy container name should not be global"
assert_contains "$PROXY_ARGS" "--name redteam-proxy-2026-03-23-120500-admin-example-com" "Proxy container name should include engagement slug"

: > "$FAKE_DOCKER_LOG"
export ENGAGEMENT_DIR="$ENG1"
stop_all_containers
STOP_ARGS="$(tr '\n' ' ' < "$FAKE_DOCKER_LOG")"

assert_contains "$STOP_ARGS" "stop redteam-proxy-2026-03-23-120000-example-com" "stop_all_containers should stop only the current engagement proxy"
assert_contains "$STOP_ARGS" "stop redteam-katana-2026-03-23-120000-example-com" "stop_all_containers should stop only the current engagement katana"
assert_not_contains "$STOP_ARGS" "ancestor=kali-redteam:latest" "stop_all_containers must not stop all redteam containers globally"
assert_not_contains "$STOP_ARGS" "redteam-proxy-2026-03-23-120500-admin-example-com" "stop_all_containers must not stop another engagement proxy"
assert_not_contains "$STOP_ARGS" "redteam-katana-2026-03-23-120500-admin-example-com" "stop_all_containers must not stop another engagement katana"

echo "[OK] Container naming and auth contracts hold"
