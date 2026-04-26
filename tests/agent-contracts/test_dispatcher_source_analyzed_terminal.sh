#!/usr/bin/env bash
set -euo pipefail

# Regression guard for the stage-based dispatcher.
# source_analyzed is a terminal source-carrier marker: once source-analyzer has
# extracted follow-up cases/surfaces, the original JS/page/data carrier must not
# remain pending and must not count as an active stage. Leaving it pending can
# strand runs with no matching downstream owner and depress recall.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="${ROOT}/.tmp-tests"
mkdir -p "$TMP_DIR"
DB="$(mktemp "${TMP_DIR}/dispatcher-source-analyzed.XXXXXX.db")"
trap 'rm -f "$DB"' EXIT

sqlite3 "$DB" <<'SQL'
CREATE TABLE cases (
  id INTEGER PRIMARY KEY,
  method TEXT,
  url TEXT,
  url_path TEXT,
  type TEXT,
  source TEXT,
  status TEXT DEFAULT 'pending',
  stage TEXT DEFAULT 'ingested',
  assigned_agent TEXT,
  consumed_at TEXT,
  query_params TEXT,
  body_params TEXT,
  path_params TEXT
);
INSERT INTO cases (id, method, url, url_path, type, source, status, stage)
VALUES (1, 'GET', 'http://example.test/main.js', '/main.js', 'javascript', 'source-analyzer', 'processing', 'ingested');
SQL

"$ROOT/agent/scripts/dispatcher.sh" "$DB" done 1 --stage source_analyzed >/dev/null

row_state="$(sqlite3 "$DB" "SELECT status || '|' || stage FROM cases WHERE id=1;")"
if [[ "$row_state" != "done|source_analyzed" ]]; then
  echo "expected source_analyzed to be terminal done, got: $row_state" >&2
  exit 1
fi

stats="$($ROOT/agent/scripts/dispatcher.sh "$DB" stats-by-stage)"
if ! grep -qF 'active (ingested|vuln_confirmed|fuzz_pending)|0' <<<"$stats"; then
  echo "expected source_analyzed to be excluded from active stage count" >&2
  echo "$stats" >&2
  exit 1
fi
if ! grep -qF 'terminal (source_analyzed|clean|exploited|errored|api_tested)|1' <<<"$stats"; then
  echo "expected source_analyzed to be counted as terminal" >&2
  echo "$stats" >&2
  exit 1
fi

# A legacy fetch must also not re-dispatch source_analyzed carriers.
fetched="$($ROOT/agent/scripts/dispatcher.sh "$DB" fetch javascript 1 source-analyzer)"
if [[ -n "$fetched" && "$fetched" != "[]" ]]; then
  echo "legacy fetch should not pull terminal source_analyzed carriers" >&2
  echo "$fetched" >&2
  exit 1
fi

echo "OK: source_analyzed is terminal and cannot strand active queue work"
