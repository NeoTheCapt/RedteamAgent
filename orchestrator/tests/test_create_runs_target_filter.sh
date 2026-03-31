#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/create-runs-filter.XXXXXX")"
MOCK_ROOT="$TMP_DIR/local-openclaw"
REQUEST_LOG="$TMP_DIR/requests.jsonl"
STATE_FILE="$TMP_DIR/mock-runs.json"
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

mkdir -p "$MOCK_ROOT/scripts/lib" "$MOCK_ROOT/state" "$TMP_DIR/orchestrator/backend/data"
cp "$REPO_ROOT/local-openclaw/scripts/create_runs.sh" "$MOCK_ROOT/scripts/create_runs.sh"
cp "$REPO_ROOT/local-openclaw/scripts/lib/orchestrator_auth.sh" "$MOCK_ROOT/scripts/lib/orchestrator_auth.sh"
chmod +x "$MOCK_ROOT/scripts/create_runs.sh"

python3 - <<'PY' "$TMP_DIR/orchestrator/backend/data/orchestrator.sqlite3"
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
con = sqlite3.connect(path)
cur = con.cursor()
cur.execute('create table projects (id integer primary key, user_id integer not null)')
cur.execute('create table sessions (token text primary key, user_id integer not null, expires_at text not null, created_at text not null)')
cur.execute('insert into projects (id, user_id) values (?, ?)', (19, 7))
cur.execute(
    'insert into sessions (token, user_id, expires_at, created_at) values (?, ?, ?, ?)',
    ('test-token', 7, '2099-04-01T00:00:00Z', '2026-04-01T00:00:00Z'),
)
con.commit()
con.close()
PY

cat >"$STATE_FILE" <<'EOF'
[
  {
    "id": 101,
    "target": "https://www.okx.com",
    "status": "running",
    "engagement_root": "/tmp/run-0101",
    "created_at": "2026-04-01 00:00:00",
    "updated_at": "2026-04-01 00:00:00",
    "ended_at": null,
    "stop_reason_code": null,
    "stop_reason_text": null
  },
  {
    "id": 201,
    "target": "http://127.0.0.1:8000",
    "status": "running",
    "engagement_root": "/tmp/run-0201",
    "created_at": "2026-04-01 00:00:00",
    "updated_at": "2026-04-01 00:00:00",
    "ended_at": null,
    "stop_reason_code": null,
    "stop_reason_text": null
  }
]
EOF

python3 - <<'PY' "$REQUEST_LOG" "$PORT_FILE" "$STATE_FILE" &
import http.server
import json
import socketserver
import sys
from pathlib import Path

request_log, port_file, state_file = map(Path, sys.argv[1:])
next_id = 300


def load_runs():
    return json.loads(state_file.read_text(encoding='utf-8'))


def save_runs(runs):
    state_file.write_text(json.dumps(runs, indent=2), encoding='utf-8')


class Handler(http.server.BaseHTTPRequestHandler):
    def _write(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with request_log.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'method': 'GET', 'path': self.path}) + '\n')
        if self.path == '/projects/19/runs':
            self._write(200, load_runs())
            return
        self._write(404, {'error': 'not found'})

    def do_POST(self):
        global next_id
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8')
        payload = json.loads(body or '{}')
        with request_log.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'method': 'POST', 'path': self.path, 'body': payload}) + '\n')
        if self.path == '/projects/19/runs':
            runs = load_runs()
            next_id += 1
            created = {
                'id': next_id,
                'target': payload['target'],
                'status': 'running',
                'engagement_root': f'/tmp/run-{next_id:04d}',
                'created_at': '2026-04-01 00:05:00',
                'updated_at': '2026-04-01 00:05:00',
                'ended_at': None,
                'stop_reason_code': None,
                'stop_reason_text': None,
            }
            runs.append(created)
            save_runs(runs)
            self._write(200, created)
            return
        self._write(404, {'error': 'not found'})

    def do_DELETE(self):
        with request_log.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'method': 'DELETE', 'path': self.path}) + '\n')
        prefix = '/projects/19/runs/'
        if self.path.startswith(prefix):
            run_id = int(self.path[len(prefix):])
            runs = [run for run in load_runs() if int(run['id']) != run_id]
            save_runs(runs)
            self._write(200, {'deleted': run_id})
            return
        self._write(404, {'error': 'not found'})

    def log_message(self, *args, **kwargs):
        return


with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
    port_file.write_text(str(server.server_address[1]), encoding='utf-8')
    server.serve_forever()
PY
SERVER_PID="$!"

for _ in $(seq 1 50); do
  [[ -f "$PORT_FILE" ]] && break
  sleep 0.1
done
[[ -f "$PORT_FILE" ]] || { echo "mock server failed to start" >&2; exit 1; }

PORT="$(cat "$PORT_FILE")"
export ORCH_BASE_URL="http://127.0.0.1:$PORT"
export ORCH_TOKEN="test-token"
export PROJECT_ID="19"
export TARGET_OKX="https://www.okx.com"
export TARGET_LOCAL="http://127.0.0.1:8000"
export TARGET_FILTER="okx"
export FORCE_REPLACE_ACTIVE_RUNS="1"
export REDTEAM_ORCHESTRATOR_DATA_DIR="$TMP_DIR/orchestrator/backend/data"

"$MOCK_ROOT/scripts/create_runs.sh" >/dev/null

python3 - <<'PY' "$STATE_FILE" "$REQUEST_LOG" "$MOCK_ROOT/state/latest-created-runs.json"
import json
import sys
from pathlib import Path

state_path, log_path, latest_path = map(Path, sys.argv[1:])
runs = json.loads(state_path.read_text(encoding='utf-8'))
requests = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
latest = json.loads(latest_path.read_text(encoding='utf-8'))

okx_runs = [run for run in runs if run['target'] == 'https://www.okx.com']
local_runs = [run for run in runs if run['target'] == 'http://127.0.0.1:8000']
assert len(okx_runs) == 1, okx_runs
assert okx_runs[0]['id'] != 101, okx_runs
assert len(local_runs) == 1 and local_runs[0]['id'] == 201, local_runs

assert any(req['method'] == 'DELETE' and req['path'] == '/projects/19/runs/101' for req in requests), requests
assert not any(req['method'] == 'DELETE' and req['path'] == '/projects/19/runs/201' for req in requests), requests
assert any(req['method'] == 'POST' and req['body']['target'] == 'https://www.okx.com' for req in requests), requests
assert not any(req['method'] == 'POST' and req['body']['target'] == 'http://127.0.0.1:8000' for req in requests), requests

assert latest['okx']['target'] == 'https://www.okx.com', latest
assert latest['local']['id'] == 201, latest
print('create_runs target filter OK')
PY
