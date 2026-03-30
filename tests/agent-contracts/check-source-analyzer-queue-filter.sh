#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCHEMA="$ROOT_DIR/agent/scripts/schema.sql"
REQUEUE_SCRIPT="$ROOT_DIR/agent/scripts/dispatcher.sh"
INGEST_SCRIPT="$ROOT_DIR/agent/scripts/recon_ingest.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -x "$REQUEUE_SCRIPT" ]] || fail "missing executable script: $REQUEUE_SCRIPT"
[[ -x "$INGEST_SCRIPT" ]] || fail "missing executable script: $INGEST_SCRIPT"
[[ -f "$SCHEMA" ]] || fail "missing schema: $SCHEMA"

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/source-queue-filter.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT

db="$tmpdir/cases.db"
sqlite3 "$db" < "$SCHEMA"

cat <<'EOF' | "$REQUEUE_SCRIPT" "$db" requeue >/dev/null
{"method":"GET","url":"https://target.local/help-center001.xml","url_path":"/help-center001.xml","type":"data","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/default001.xml","url_path":"/default001.xml","type":"data","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/account/login","url_path":"/account/login","type":"page","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/api/v1/config","url_path":"/api/v1/config","type":"api","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/docs-v5/broker_en/","url_path":"/docs-v5/broker_en/","type":"page","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/ftp/incident-support.kdbx","url_path":"/ftp/incident-support.kdbx","type":"data","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/ftp/acquisitions.md","url_path":"/ftp/acquisitions.md","type":"data","source":"source-analyzer"}
{"method":"GET","url":"https://target.local/default-index.xml","url_path":"/default-index.xml","type":"data","source":"recon-specialist"}
EOF

python3 - <<'PY' "$db"
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(db)
rows = con.execute("select source, type, url_path from cases order by id").fetchall()
assert rows == [
    ("source-analyzer", "page", "/account/login"),
    ("source-analyzer", "api", "/api/v1/config"),
    ("source-analyzer", "page", "/docs-v5/broker_en/"),
    ("source-analyzer", "data", "/ftp/incident-support.kdbx"),
    ("source-analyzer", "data", "/ftp/acquisitions.md"),
    ("recon-specialist", "data", "/default-index.xml"),
], rows
PY

rm -f "$db"
sqlite3 "$db" < "$SCHEMA"

cat <<'EOF' | "$INGEST_SCRIPT" "$db" source-analyzer >/dev/null
{"method":"GET","url":"https://target.local/help-center001.xml","url_path":"/help-center001.xml","type":"data"}
{"method":"GET","url":"https://target.local/account/security-reset","url_path":"/account/security-reset","type":"page"}
{"method":"GET","url":"https://target.local/swagger.json","url_path":"/swagger.json","type":"api-spec"}
{"method":"GET","url":"https://target.local/ftp/incident-support.kdbx","url_path":"/ftp/incident-support.kdbx","type":"data"}
EOF

python3 - <<'PY' "$db"
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(db)
rows = con.execute("select source, type, url_path from cases order by id").fetchall()
assert rows == [
    ("source-analyzer", "page", "/account/security-reset"),
    ("source-analyzer", "api-spec", "/swagger.json"),
    ("source-analyzer", "data", "/ftp/incident-support.kdbx"),
], rows
PY

echo "source-analyzer queue filter: ok"
