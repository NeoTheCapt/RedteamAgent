#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/orch-auth-env.XXXXXX")"
ENV_FILE="$TMP_DIR/scheduler.env"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

cat >"$ENV_FILE" <<'EOF'
# Existing scheduler env
ORCH_TOKEN=old-token
PROJECT_ID=19
TARGET_LOCAL=
EOF

export LOCAL_OPENCLAW_ENV_FILE="$ENV_FILE"
export PROJECT_ID=19
export ORCH_BASE_URL=
export TARGET_OKX=
export TARGET_LOCAL=
export OBSERVATION_SECONDS=
export OPENCLAW_BIN=
export OPENCLAW_SKILL=
export OPENCLAW_TIMEOUT_SECONDS=
export REPORT_CHANNEL=
export REPORT_TO=

# shellcheck disable=SC1091
source "$REPO_ROOT/local-openclaw/scripts/lib/orchestrator_auth.sh"
_update_scheduler_env_token "fresh-token"

python3 - <<'PY' "$ENV_FILE"
import sys
from pathlib import Path

path = Path(sys.argv[1])
content = path.read_text(encoding='utf-8')
lines = [line for line in content.splitlines() if line and not line.startswith('#')]
parsed = dict(line.split('=', 1) for line in lines)

assert parsed['ORCH_TOKEN'] == 'fresh-token', parsed
assert parsed['PROJECT_ID'] == '19', parsed
assert parsed['ORCH_BASE_URL'] == 'http://127.0.0.1:18000', parsed
assert parsed['TARGET_OKX'] == 'https://www.okx.com', parsed
assert parsed['TARGET_LOCAL'] == 'http://127.0.0.1:8000', parsed
assert parsed['OBSERVATION_SECONDS'] == '300', parsed
assert parsed['OPENCLAW_BIN'] == '/opt/homebrew/bin/openclaw', parsed
assert parsed['OPENCLAW_SKILL'] == 'scan-optimizer-loop', parsed
assert parsed['OPENCLAW_TIMEOUT_SECONDS'] == '1800', parsed
print('orchestrator auth token refresh preserves scheduler env and backfills defaults OK')
PY
