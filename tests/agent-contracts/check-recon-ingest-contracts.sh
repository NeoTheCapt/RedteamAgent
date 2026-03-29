#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCRIPT="$ROOT_DIR/agent/scripts/recon_ingest.sh"
SCHEMA="$ROOT_DIR/agent/scripts/schema.sql"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -x "$SCRIPT" ]] || fail "missing executable script: $SCRIPT"
[[ -f "$SCHEMA" ]] || fail "missing schema: $SCHEMA"

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/recon-ingest.XXXXXX")
db="$tmpdir/cases.db"
sqlite3 "$db" < "$SCHEMA"

cat <<'EOF' | "$SCRIPT" "$db" source-analyzer >/dev/null
{"method":"POST","url":"https://target.local/rest/user/login","url_path":"/rest/user/login","type":"api","query_params":{},"body_params":{"email":"demo@target.local","password":"Password123!"},"path_params":{},"cookie_params":{"sid":"abc123"}}
{"method":"GET","url":"https://target.local/rest/products/42/reviews?limit=5","url_path":"/rest/products/42/reviews","type":"api","query_params":{"limit":"5"},"body_params":{},"path_params":{"seg_3":"42"}}
{"method":"PUT","url":"https://target.local/rest/continue-code-fixIt/apply/<continueCode>","type":"api"}
{"method":"GET","url":"https://target.local/swagger/*","type":"api"}
EOF

python3 - <<'PY' "$db"
import json
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(db)
rows = con.execute(
    "select method,url_path,query_params,body_params,path_params,cookie_params,type,source,params_key_sig from cases order by id"
).fetchall()
assert len(rows) == 2, rows

post = rows[0]
assert post[0] == "POST", post
assert post[1] == "/rest/user/login", post
assert json.loads(post[3])["email"] == "demo@target.local", post
assert json.loads(post[3])["password"] == "Password123!", post
assert json.loads(post[5])["sid"] == "abc123", post
assert post[6] == "api", post
assert post[7] == "source-analyzer", post

get = rows[1]
assert get[0] == "GET", get
assert get[1] == "/rest/products/42/reviews", get
assert json.loads(get[2])["limit"] == "5", get
assert json.loads(get[4])["seg_3"] == "42", get
assert get[6] == "api", get
PY

rm -rf "$tmpdir"
echo "recon ingest contracts: ok"
