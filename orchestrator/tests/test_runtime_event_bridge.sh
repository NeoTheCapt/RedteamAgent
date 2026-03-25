#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-bridge.XXXXXX")"
REQUEST_LOG="$TMP_DIR/requests.jsonl"
PORT_FILE="$TMP_DIR/port.txt"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

python3 - <<'PY' "$REQUEST_LOG" "$PORT_FILE" &
import http.server
import json
import socketserver
import sys

request_log, port_file = sys.argv[1:]

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        with open(request_log, "a", encoding="utf-8") as fh:
            fh.write(body + "\n")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args, **kwargs):
        return

with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
    with open(port_file, "w", encoding="utf-8") as fh:
        fh.write(str(server.server_address[1]))
    server.serve_forever()
PY
SERVER_PID="$!"

for _ in $(seq 1 50); do
  [[ -f "$PORT_FILE" ]] && break
  sleep 0.1
done
[[ -f "$PORT_FILE" ]] || { echo "mock server failed to start" >&2; exit 1; }

PORT="$(cat "$PORT_FILE")"
export ORCHESTRATOR_BASE_URL="http://127.0.0.1:$PORT"
export ORCHESTRATOR_TOKEN="test-token"
export ORCHESTRATOR_PROJECT_ID="11"
export ORCHESTRATOR_RUN_ID="22"
export ORCHESTRATOR_PHASE="recon"

bash "$REPO_ROOT/agent/scripts/emit_runtime_event.sh" \
  "phase.started" \
  "recon" \
  "operator" \
  "operator" \
  "Recon started"

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"
cat >"$ENG_DIR/log.md" <<'EOF'
# Engagement Log
EOF
cat >"$ENG_DIR/findings.md" <<'EOF'
# Findings

- **Finding Count**: 0
EOF
touch "$ENG_DIR/surfaces.jsonl"

BODY_FILE="$TMP_DIR/finding.md"
cat >"$BODY_FILE" <<'EOF'
## [FINDING-ID] Sample finding

Proof
EOF

"$REPO_ROOT/agent/scripts/append_log_entry.sh" "$ENG_DIR" "operator" "Recon start" "Kick off recon" "Queued subagents"
"$REPO_ROOT/agent/scripts/append_finding.sh" "$ENG_DIR" "vulnerability-analyst" "$BODY_FILE" >/dev/null
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "object_reference" "https://target.example/orders/7" "source-analyzer" "Observed direct object path" "log.md" "covered"

python3 - <<'PY' "$REQUEST_LOG"
import json
import sys

request_log = sys.argv[1]
with open(request_log, "r", encoding="utf-8") as fh:
    rows = [json.loads(line) for line in fh if line.strip()]

event_types = {row["event_type"] for row in rows}
expected = {"phase.started", "artifact.updated", "finding.created", "surface.updated"}
missing = expected - event_types
if missing:
    raise SystemExit(f"missing event types: {sorted(missing)}")
PY
