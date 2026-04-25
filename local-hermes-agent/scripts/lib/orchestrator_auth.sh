#!/usr/bin/env bash
set -euo pipefail

LOCAL_HERMES_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_HERMES_STATE_DIR="$LOCAL_HERMES_ROOT/state"
LOCAL_HERMES_REPO_ROOT="$(cd "$LOCAL_HERMES_ROOT/.." && pwd)"
DEFAULT_ORCH_DATA_DIR="$LOCAL_HERMES_REPO_ROOT/orchestrator/backend/data"
DEFAULT_SCHEDULER_ENV_FILE="$LOCAL_HERMES_STATE_DIR/scheduler.env"

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

load_scheduler_env_if_needed() {
  local env_file="${LOCAL_HERMES_ENV_FILE:-$DEFAULT_SCHEDULER_ENV_FILE}"

  # The unattended loop often invokes helper scripts directly from a clean shell.
  # When PROJECT_ID is missing, fall back to the repo-local scheduler env so
  # build_context.sh / create_runs.sh / run_cycle_prep.sh can still run without
  # the caller having to pre-source local-hermes-agent/state/scheduler.env.
  [[ -n "${PROJECT_ID:-}" ]] && return 0
  [[ -f "$env_file" ]] || return 0

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

load_scheduler_env_if_needed

orchestrator_db_path() {
  local data_dir="${REDTEAM_ORCHESTRATOR_DATA_DIR:-$DEFAULT_ORCH_DATA_DIR}"
  printf '%s/orchestrator.sqlite3\n' "$data_dir"
}

_update_scheduler_env_token() {
  local next_token="${1:-}"
  [[ -n "$next_token" ]] || return 0

  local env_file="${LOCAL_HERMES_ENV_FILE:-$DEFAULT_SCHEDULER_ENV_FILE}"
  [[ -f "$env_file" ]] || return 0

  ORCH_AUTH_ENV_FILE="$env_file" ORCH_AUTH_NEXT_TOKEN="$next_token" python3 <<'PY'
import os
import tempfile
from pathlib import Path

path = Path(os.environ["ORCH_AUTH_ENV_FILE"])
next_token = os.environ["ORCH_AUTH_NEXT_TOKEN"]
raw_text = path.read_text(encoding="utf-8") if path.exists() else ""
lines = raw_text.splitlines()

required_order = [
    "ORCH_TOKEN",
    "PROJECT_ID",
    "ORCH_BASE_URL",
    "TARGET_OKX",
    "TARGET_LOCAL",
    "OBSERVATION_SECONDS",
    "HERMES_BIN",
    "HERMES_SKILL",
    "HERMES_TIMEOUT_SECONDS",
    "REPORT_CHANNEL",
    "REPORT_TO",
]
default_values = {
    "ORCH_BASE_URL": "http://127.0.0.1:18000",
    "TARGET_OKX": "https://www.okx.com",
    "TARGET_LOCAL": "http://127.0.0.1:8000",
    "OBSERVATION_SECONDS": "300",
    "HERMES_BIN": "/opt/homebrew/bin/openclaw",
    "HERMES_SKILL": "scan-optimizer-loop",
    "HERMES_TIMEOUT_SECONDS": "1800",
    "REPORT_CHANNEL": "",
    "REPORT_TO": "",
}
required_values = {
    key: (os.environ.get(key, "") or default_values.get(key, ""))
    for key in required_order
}
required_values["ORCH_TOKEN"] = next_token

updated = False
seen_keys: set[str] = set()
for index, line in enumerate(lines):
    if line.startswith("#") or "=" not in line:
        continue
    key, _sep, existing_value = line.partition("=")
    if key in required_values:
        next_value = required_values[key]
        if key != "ORCH_TOKEN" and next_value == "":
            next_value = existing_value
            required_values[key] = existing_value
        lines[index] = f"{key}={next_value}"
        seen_keys.add(key)
        updated = True

if not updated and not lines:
    lines = ["# Auto-repaired scheduler env"]

for key in required_order:
    if key not in seen_keys and required_values[key] != "":
        lines.append(f"{key}={required_values[key]}")

content = "\n".join(lines).rstrip("\n") + "\n"
import fcntl
lock_path = path.parent / (path.name + ".lock")
lock_fd = open(lock_path, "w")
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
    os.chmod(path, 0o600)
except BlockingIOError:
    pass
finally:
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()
PY
}

_refresh_orchestrator_token() {
  local cooldown_file="$LOCAL_HERMES_STATE_DIR/.token-refresh-ts"
  local cooldown="${HERMES_TOKEN_REFRESH_COOLDOWN_SECONDS:-30}"
  if [[ -f "$cooldown_file" ]]; then
    local last_refresh
    last_refresh="$(cat "$cooldown_file" 2>/dev/null || echo 0)"
    local now
    now="$(date +%s)"
    if (( now - last_refresh < cooldown )); then
      return 0
    fi
  fi

  local db_path
  db_path="$(orchestrator_db_path)"

  if [[ ! -f "$db_path" ]]; then
    echo "orchestrator auth refresh failed: database not found at $db_path" >&2
    return 1
  fi

  local resolution_json
  resolution_json="$(
    ORCH_AUTH_DB_PATH="$db_path" \
    ORCH_AUTH_PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}" \
    ORCH_AUTH_CURRENT_TOKEN="${ORCH_TOKEN:-}" \
    ORCH_AUTH_TTL_HOURS="${HERMES_SESSION_TTL_HOURS:-24}" \
    python3 <<'PY'
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path


def fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


db_path = Path(os.environ["ORCH_AUTH_DB_PATH"])
project_id = int(os.environ["ORCH_AUTH_PROJECT_ID"])
current_token = os.environ.get("ORCH_AUTH_CURRENT_TOKEN", "").strip()
ttl_hours = int(os.environ.get("ORCH_AUTH_TTL_HOURS", "24"))
now = datetime.now(UTC)
now_text = fmt(now)
expiry_text = fmt(now + timedelta(hours=ttl_hours))

connection = sqlite3.connect(db_path)
connection.row_factory = sqlite3.Row
project = connection.execute(
    "SELECT user_id FROM projects WHERE id = ?",
    (project_id,),
).fetchone()
if project is None:
    raise SystemExit(f"project {project_id} not found in {db_path}")
user_id = int(project["user_id"])


def token_is_valid(token: str) -> bool:
    if not token:
        return False
    row = connection.execute(
        "SELECT 1 FROM sessions WHERE token = ? AND user_id = ? AND expires_at > ? LIMIT 1",
        (token, user_id, now_text),
    ).fetchone()
    return row is not None

source = ""
token = ""

if current_token and token_is_valid(current_token):
    source = "current"
    token = current_token
else:
    row = connection.execute(
        "SELECT token FROM sessions WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (user_id, now_text),
    ).fetchone()
    if row is not None:
        source = "existing_session"
        token = str(row["token"])
    else:
        token = secrets.token_urlsafe(32)
        connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expiry_text),
        )
        connection.commit()
        source = "minted_session"

print(json.dumps({"token": token, "source": source, "user_id": user_id}))
PY
)"

  local next_token source
  next_token="$(printf '%s' "$resolution_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
  source="$(printf '%s' "$resolution_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source"])')"

  if [[ -z "$next_token" ]]; then
    echo "orchestrator auth refresh failed: no token resolved" >&2
    return 1
  fi

  local previous_token="${ORCH_TOKEN:-}"
  export ORCH_TOKEN="$next_token"

  if [[ "$previous_token" != "$next_token" ]]; then
    _update_scheduler_env_token "$next_token"
    case "$source" in
      existing_session)
        echo "resolved fresh ORCH_TOKEN from orchestrator DB (reused latest valid session)." >&2
        ;;
      minted_session)
        echo "resolved fresh ORCH_TOKEN from orchestrator DB (minted local scheduler session)." >&2
        ;;
    esac
  fi
  date +%s > "$LOCAL_HERMES_STATE_DIR/.token-refresh-ts" 2>/dev/null || true
}

ensure_orchestrator_token() {
  _refresh_orchestrator_token
}

orchestrator_curl() {
  local tmp_file http_code curl_status attempt
  ensure_orchestrator_token

  for attempt in 1 2; do
    tmp_file="$(mktemp)"
    set +e
    http_code="$(curl -sS -o "$tmp_file" -w '%{http_code}' -H "Authorization: Bearer $ORCH_TOKEN" "$@")"
    curl_status=$?
    set -e

    if [[ $curl_status -ne 0 ]]; then
      [[ -s "$tmp_file" ]] && cat "$tmp_file" >&2
      rm -f "$tmp_file"
      return "$curl_status"
    fi

    if [[ "$http_code" == "401" && "$attempt" -eq 1 ]]; then
      rm -f "$tmp_file"
      ORCH_TOKEN=""
      export ORCH_TOKEN
      _refresh_orchestrator_token
      continue
    fi

    if [[ ! "$http_code" =~ ^2 ]]; then
      if [[ -s "$tmp_file" ]]; then
        cat "$tmp_file" >&2
      else
        echo "orchestrator API request failed with HTTP $http_code" >&2
      fi
      rm -f "$tmp_file"
      return 22
    fi

    cat "$tmp_file"
    rm -f "$tmp_file"
    return 0
  done

  echo "orchestrator API request failed after token refresh" >&2
  return 22
}
