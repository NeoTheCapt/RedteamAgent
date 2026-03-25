#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-redteam-allinone:dev}"
TMP_ENV=$(mktemp)
trap 'rm -f "$TMP_ENV"' EXIT

cat > "$TMP_ENV" <<'EOF'
OPENAI_API_KEY=dummy
REDTEAM_RUNTIME_MODE=local
EOF

docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "[FAIL] image not found: $IMAGE" >&2
  exit 1
}

docker run --rm --entrypoint /bin/bash --env-file "$TMP_ENV" "$IMAGE" -lc '
set -euo pipefail
test -d /opt/redteam-agent/.opencode
test -f /opt/redteam-agent/scripts/lib/container.sh
test "$(printenv REDTEAM_RUNTIME_MODE)" = "local"
command -v opencode >/dev/null
command -v nmap >/dev/null
command -v ffuf >/dev/null
command -v sqlmap >/dev/null
command -v mitmdump >/dev/null
command -v katana >/dev/null
command -v chromium >/dev/null
command -v msfrpcd >/dev/null
katana -version >/dev/null
chromium --version >/dev/null
mkdir -p /tmp/katana-e2e
cat > /tmp/katana-e2e/index.html <<EOF
<html><body><a href="/about">About</a></body></html>
EOF
cat > /tmp/katana-e2e/about <<EOF
ok
EOF
python3 -m http.server 8124 --directory /tmp/katana-e2e >/tmp/katana-http.log 2>&1 &
HTTP_PID=$!
trap "kill $HTTP_PID 2>/dev/null || true" EXIT
for _ in $(seq 1 20); do
  curl -sf http://127.0.0.1:8124/ >/dev/null && break
  sleep 0.2
done
katana -u http://127.0.0.1:8124/ -hl -jc -system-chrome -system-chrome-path /usr/bin/chromium -headless-options --no-sandbox,--disable-dev-shm-usage,--disable-gpu -d 1 -jsonl -silent -o /tmp/katana.jsonl >/tmp/katana-run.log 2>&1
test -s /tmp/katana.jsonl
grep -Eq "127\\.0\\.0\\.1:8124|/about" /tmp/katana.jsonl
'

echo "[OK] single-image runtime contracts passed"
