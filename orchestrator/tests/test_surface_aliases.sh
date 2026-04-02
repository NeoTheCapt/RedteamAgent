#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/surface-aliases.XXXXXX")"
ENG_DIR="$TMP_DIR/engagement"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$ENG_DIR"
touch "$ENG_DIR/surfaces.jsonl"

"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "auth_surface" "/auth/login" "test" "alias auth surface" "evidence" "deferred"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "anti_automation" "/rest/captcha/" "test" "alias anti automation surface" "evidence" "discovered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "update_distribution" "/downloads/appcast.xml" "test" "alias update surface" "evidence" "covered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "cors_surface" "/public/data" "test" "alias cors surface" "evidence" "discovered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "opaque_post_contract" "/priapi/v5/rubik/discover2/market" "test" "alias opaque contract surface" "evidence" "discovered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "admin_session" "/session/admin" "test" "alias admin session surface" "evidence" "covered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "authenticated_admin_api" "/rest/admin/application-configuration" "test" "alias authenticated admin api surface" "evidence" "discovered"
"$REPO_ROOT/agent/scripts/append_surface.sh" "$ENG_DIR" "authenticated_api" "/priapi/v1/wallet/web/coin/main" "test" "alias authenticated api surface" "evidence" "discovered"

cat >"$TMP_DIR/aliases.jsonl" <<'EOF'
{"surface_type":"auth_surface","target":"/auth/sso","source":"jsonl","rationale":"alias auth jsonl","status":"deferred"}
{"surface_type":"anti_automation","target":"/rest/image-captcha/","source":"jsonl","rationale":"alias anti automation jsonl","status":"discovered"}
{"surface_type":"update_distribution","target":"/downloads/manifest.json","source":"jsonl","rationale":"alias update jsonl","status":"covered"}
{"surface_type":"cors_surface","target":"/public/json","source":"jsonl","rationale":"alias cors jsonl","status":"discovered"}
{"surface_type":"opaque_post_contract","target":"/priapi/v1/dx/trade/multi/web/order/save/broadcast","source":"jsonl","rationale":"alias opaque contract jsonl","status":"discovered"}
{"surface_type":"reflected_input","target":"/priapi/v1/dx/trade/multi/tokens/v2/search","source":"jsonl","rationale":"alias reflected input jsonl","status":"discovered"}
{"surface_type":"distribution_artifact","target":"/upgradeapp/android.apk","source":"jsonl","rationale":"alias distribution artifact jsonl","status":"discovered"}
{"surface_type":"admin_session","target":"/session/admin/jsonl","source":"jsonl","rationale":"alias admin session jsonl","status":"covered"}
{"surface_type":"authenticated_admin_api","target":"/rest/user/whoami","source":"jsonl","rationale":"alias authenticated admin api jsonl","status":"covered"}
{"surface_type":"authenticated_api","target":"/priapi/v1/dx/market/v2/twitter/content/list","source":"jsonl","rationale":"alias authenticated api jsonl","status":"discovered"}
EOF
"$REPO_ROOT/agent/scripts/append_surface_jsonl.sh" "$ENG_DIR" <"$TMP_DIR/aliases.jsonl"

python3 - <<'PY' "$ENG_DIR/surfaces.jsonl"
import json
import sys
from collections import Counter

path = sys.argv[1]
rows = [json.loads(line) for line in open(path, 'r', encoding='utf-8') if line.strip()]
counts = Counter(row['surface_type'] for row in rows)
assert counts['auth_entry'] == 4, counts
assert counts['file_handling'] == 3, counts
assert counts['cors_review'] == 2, counts
assert counts['api_param_followup'] == 3, counts
assert counts['workflow_token'] == 2, counts
assert counts['privileged_write'] == 4, counts
assert 'auth_surface' not in counts, counts
assert 'update_distribution' not in counts, counts
assert 'cors_surface' not in counts, counts
assert 'opaque_post_contract' not in counts, counts
assert 'reflected_input' not in counts, counts
assert 'distribution_artifact' not in counts, counts
assert 'admin_session' not in counts, counts
assert 'authenticated_admin_api' not in counts, counts
assert 'authenticated_api' not in counts, counts
print('surface alias canonicalization OK')
PY
