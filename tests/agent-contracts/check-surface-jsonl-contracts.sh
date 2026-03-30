#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"
printf '' > "$ENG_DIR/surfaces.jsonl"
cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"]
}
EOF

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"surface_type":"object_reference","target":"GET /orders/7","source":"source-analyzer","rationale":"bundle shows direct order fetch","evidence_ref":"downloads/app.js","status":"discovered"}
EOF

grep -q '"surface_type": "object_reference"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET /orders/7"' "$ENG_DIR/surfaces.jsonl"

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"category":"auth-workflow","path":"*/account/login-pwd/forget, */account/oauth","source":"source-analyzer","reason":"robots discloses recovery and auth-flow route families","priority":"medium"}
{"surface_type":"identity_verification","target":"*/kyc$, */kyb/","source":"source-analyzer","rationale":"robots discloses onboarding and verification routes","status":"discovered"}
{"surface_type":"p2p_trading","target":"*/p2p/order, */p2p/dispute","source":"source-analyzer","rationale":"robots reveals transaction and dispute workflow families","status":"discovered"}
EOF

grep -q '"surface_type": "account_recovery"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET \*/account/login-pwd/forget, \*/account/oauth"' "$ENG_DIR/surfaces.jsonl"
grep -q '"surface_type": "auth_entry"' "$ENG_DIR/surfaces.jsonl"
grep -q '"surface_type": "dynamic_render"' "$ENG_DIR/surfaces.jsonl"

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"path":"/buy-crypto","source_case_id":56,"reason":"Concrete application route referenced in public landing-page JSON.","source":"vulnerability-analyst"}
{"path":"/trade-spot/btc-usdt","source_case_id":56,"reason":"Concrete trading route referenced in public landing-page JSON.","source":"vulnerability-analyst"}
{"path":"/historical-data","source_case_id":61,"reason":"Concrete route referenced in banner/config HTML content.","source":"vulnerability-analyst"}
EOF

grep -q '"target": "GET /buy-crypto"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET /trade-spot/btc-usdt"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET /historical-data"' "$ENG_DIR/surfaces.jsonl"

dynamic_render_count=$(grep -c '"surface_type": "dynamic_render"' "$ENG_DIR/surfaces.jsonl")
[[ "$dynamic_render_count" -ge 4 ]]

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"url":"http://127.0.0.1:8000/b2b/v2/orders","method":"POST","type":"api","auth":"bearer-jwt","notes":"Swagger-documented B2B endpoint; request body requires cid and orderLines/orderLinesData"}
{"url":"http://127.0.0.1:8000/ftp/incident-support.kdbx","method":"GET","type":"file","auth":"none","notes":"Public KeePass database; likely broader credential/secrets yield than current app-only admin JWT"}
{"url":"http://127.0.0.1:8000/rest/2fa/disable","method":"POST","type":"api","auth":"cookie-jwt","notes":"Authenticated 2FA management surface from main.js"}
{"url":"http://127.0.0.1:8000/rest/user/change-password","method":"GET","type":"api","auth":"cookie-jwt","notes":"Password change uses query-string secrets; high-value for replay/log leakage testing"}
EOF

grep -q '"surface_type": "api_documentation"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "POST http://127.0.0.1:8000/b2b/v2/orders"' "$ENG_DIR/surfaces.jsonl"
grep -q '"surface_type": "file_handling"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET http://127.0.0.1:8000/ftp/incident-support.kdbx"' "$ENG_DIR/surfaces.jsonl"
grep -q '"surface_type": "workflow_token"' "$ENG_DIR/surfaces.jsonl"
grep -q '"surface_type": "privileged_write"' "$ENG_DIR/surfaces.jsonl"

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"url":"http://host.docker.internal:8000/rest/admin","method":"GET","type":"page","reason":"Container-local alias should collapse back to the scoped loopback target"}
{"url":"http://localhost:3000/.well-known/csaf/provider-metadata.json","method":"GET","type":"api-docs","reason":"Cross-origin loopback CSAF reference should not be imported as an in-scope surface"}
EOF

grep -q '"target": "GET http://127.0.0.1:8000/rest/admin"' "$ENG_DIR/surfaces.jsonl"
! grep -q 'localhost:3000' "$ENG_DIR/surfaces.jsonl"

cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"url":"https://okg-pub-hk.oss-accelerate.aliyuncs.com/upgradeapp/install-manifest2.plist","type":"asset-distribution","reason":"Public download API exposes external mobile install manifest host"}
{"url":"https://static.coinall.ltd/","type":"cdn-asset-host","reason":"Public market-data API references external icon CDN host"}
EOF

grep -q '"target": "GET https://okg-pub-hk.oss-accelerate.aliyuncs.com/upgradeapp/install-manifest2.plist"' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET https://static.coinall.ltd/"' "$ENG_DIR/surfaces.jsonl"

before_count=$(wc -l < "$ENG_DIR/surfaces.jsonl")
cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"surface_type":"account_recovery","target":"PUT http://127.0.0.1:8000/rest/continue-code-fixIt/apply/<continueCode>","source":"vulnerability-analyst","rationale":"templated continuation segment is not concrete","status":"discovered"}
{"surface_type":"workflow_token","target":"GET /real/session/token","source":"source-analyzer","rationale":"concrete token endpoint remains importable","status":"discovered"}
EOF

after_count=$(wc -l < "$ENG_DIR/surfaces.jsonl")
[[ "$after_count" -eq $((before_count + 1)) ]]
! grep -q '<continueCode>' "$ENG_DIR/surfaces.jsonl"
grep -q '"target": "GET /real/session/token"' "$ENG_DIR/surfaces.jsonl"

before_count=$(wc -l < "$ENG_DIR/surfaces.jsonl")
cat <<'EOF' | "$ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR"
{"surface_type":"account_recovery","target":"POST /rest/user/reset-password and GET /rest/user/security-question?email=<email>","source":"source-analyzer","rationale":"mixed advisory should preserve the concrete recovery flow while normalizing the templated fragment","status":"discovered"}
EOF

after_count=$(wc -l < "$ENG_DIR/surfaces.jsonl")
[[ "$after_count" -eq $((before_count + 1)) ]]
grep -q '"target": "POST /rest/user/reset-password and GET /rest/user/security-question?email=..."' "$ENG_DIR/surfaces.jsonl"
! grep -q 'security-question?email=<email>' "$ENG_DIR/surfaces.jsonl"

echo "surface jsonl contracts: ok"
