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
cat > "$tmpdir/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"]
}
EOF

cat <<'EOF' | "$SCRIPT" "$db" source-analyzer >/dev/null
{"method":"POST","url":"http://host.docker.internal:8000/rest/user/login","url_path":"/rest/user/login","type":"api","query_params":{},"body_params":{"email":"demo@target.local","password":"Password123!"},"path_params":{},"cookie_params":{"sid":"abc123"}}
{"method":"GET","url":"http://localhost:3000/.well-known/csaf/provider-metadata.json","url_path":"/.well-known/csaf/provider-metadata.json","type":"data"}
{"method":"GET","url":"http://127.0.0.1:8000/rest/products/42/reviews?limit=5","url_path":"/rest/products/42/reviews","type":"api","query_params":{"limit":"5"},"body_params":{},"path_params":{"seg_3":"42"}}
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
    "select method,url,url_path,query_params,body_params,path_params,cookie_params,type,source,params_key_sig from cases order by id"
).fetchall()
assert len(rows) == 2, rows

post = rows[0]
assert post[0] == "POST", post
assert post[1] == "http://127.0.0.1:8000/rest/user/login", post
assert post[2] == "/rest/user/login", post
assert json.loads(post[4])["email"] == "demo@target.local", post
assert json.loads(post[4])["password"] == "Password123!", post
assert json.loads(post[6])["sid"] == "abc123", post
assert post[7] == "api", post
assert post[8] == "source-analyzer", post

get = rows[1]
assert get[0] == "GET", get
assert get[1] == "http://127.0.0.1:8000/rest/products/42/reviews?limit=5", get
assert get[2] == "/rest/products/42/reviews", get
assert json.loads(get[3])["limit"] == "5", get
assert json.loads(get[5])["seg_3"] == "42", get
assert get[7] == "api", get
assert get[8] == "source-analyzer", get
assert not any("localhost:3000" in row[1] for row in rows), rows
PY

rm -rf "$tmpdir"
echo "recon ingest contracts: ok"
