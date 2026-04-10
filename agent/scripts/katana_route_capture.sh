#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 <engagement_dir> <route_url_or_path> [label]" >&2
    exit 1
fi

ENGAGEMENT_DIR_RAW="$1"
ROUTE_SPEC="$2"
LABEL="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/container.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/loopback_scope.sh"

if [[ "$ENGAGEMENT_DIR_RAW" = /* ]]; then
    export ENGAGEMENT_DIR="$ENGAGEMENT_DIR_RAW"
else
    export ENGAGEMENT_DIR="$(cd "$ENGAGEMENT_DIR_RAW" && pwd)"
fi

[[ -d "$ENGAGEMENT_DIR" ]] || {
    echo "engagement dir not found: $ENGAGEMENT_DIR" >&2
    exit 1
}

_resolve_engagement_dir >/dev/null
SCOPE_FILE="$ENGAGEMENT_DIR_ABS/scope.json"
[[ -f "$SCOPE_FILE" ]] || {
    echo "scope.json not found in $ENGAGEMENT_DIR_ABS" >&2
    exit 1
}

ROUTE_URL="$(python3 - "$SCOPE_FILE" "$ROUTE_SPEC" <<'PY'
import json, sys
from urllib.parse import urljoin, urlparse

scope = json.load(open(sys.argv[1], encoding='utf-8'))
spec = sys.argv[2].strip()
if not spec:
    raise SystemExit('route spec is empty')
base = scope.get('target') or ''
if not base:
    raise SystemExit('scope target missing')
base_parsed = urlparse(base)
if spec.startswith(('http://', 'https://')):
    resolved = spec
else:
    normalized = spec
    if normalized.startswith('#/'):
        normalized = '/' + normalized
    elif not normalized.startswith('/'):
        normalized = '/' + normalized.lstrip('/')
    if normalized.startswith('/#/'):
        resolved = f"{base_parsed.scheme}://{base_parsed.netloc}{normalized}"
    else:
        resolved = urljoin(base, normalized)
parsed = urlparse(resolved)
if not parsed.scheme or not parsed.netloc:
    raise SystemExit(f'unusable route url: {resolved}')
allowed = {str(scope.get('hostname') or '').strip().lower()}
for item in scope.get('scope') or []:
    item = str(item or '').strip().lower()
    if item:
        allowed.add(item)
host = (parsed.hostname or '').lower()
loopback = {'127.0.0.1', 'localhost', '0.0.0.0', '::1', 'host.docker.internal'}
def in_scope(hostname: str) -> bool:
    if hostname in loopback:
        return True
    for entry in allowed:
        if not entry:
            continue
        if hostname == entry:
            return True
        if entry.startswith('*.'):
            suffix = entry[2:]
            if hostname == suffix or hostname.endswith('.' + suffix):
                return True
    return False
if not in_scope(host):
    raise SystemExit(f'route host out of scope: {host}')
print(resolved)
PY
)"

RUNTIME_ROUTE_URL="$(_rewrite_runtime_target_arg "$ROUTE_URL")"

SLUG="$(python3 - "$ROUTE_URL" "$LABEL" <<'PY'
import hashlib, re, sys
from urllib.parse import urlparse
url = sys.argv[1]
label = sys.argv[2].strip()
parsed = urlparse(url)
parts = [parsed.path or '/']
if parsed.fragment:
    parts.append(parsed.fragment)
if parsed.query:
    parts.append(parsed.query)
if label:
    parts.append(label)
raw = '-'.join(parts)
slug = re.sub(r'[^a-zA-Z0-9._-]+', '-', raw).strip('-').lower() or 'route'
slug = slug[:80].rstrip('-') or 'route'
print(f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:10]}")
PY
)"

OUT_DIR="$ENGAGEMENT_DIR_ABS/scans/route-captures"
mkdir -p "$OUT_DIR"
RAW_OUT="$OUT_DIR/${SLUG}.jsonl"
ERR_OUT="$OUT_DIR/${SLUG}.error.log"
SUMMARY_OUT="$OUT_DIR/${SLUG}.summary.json"
TMP_OUT="$OUT_DIR/.${SLUG}.tmp.jsonl"
trap 'rm -f "$TMP_OUT"' EXIT
: > "$TMP_OUT"
: > "$ERR_OUT"

KATANA_ROUTE_CAPTURE_DEPTH="${KATANA_ROUTE_CAPTURE_DEPTH:-1}"
KATANA_ROUTE_CAPTURE_DURATION="${KATANA_ROUTE_CAPTURE_DURATION:-20s}"
KATANA_ROUTE_CAPTURE_TIMEOUT_SECONDS="${KATANA_ROUTE_CAPTURE_TIMEOUT_SECONDS:-20}"
KATANA_ROUTE_CAPTURE_TIME_STABLE_SECONDS="${KATANA_ROUTE_CAPTURE_TIME_STABLE_SECONDS:-6}"
KATANA_ROUTE_CAPTURE_RETRY_COUNT="${KATANA_ROUTE_CAPTURE_RETRY_COUNT:-1}"
KATANA_ROUTE_CAPTURE_MAX_FAILURE_COUNT="${KATANA_ROUTE_CAPTURE_MAX_FAILURE_COUNT:-5}"
KATANA_ROUTE_CAPTURE_CONCURRENCY="${KATANA_ROUTE_CAPTURE_CONCURRENCY:-4}"
KATANA_ROUTE_CAPTURE_PARALLELISM="${KATANA_ROUTE_CAPTURE_PARALLELISM:-2}"
KATANA_ROUTE_CAPTURE_RATE_LIMIT="${KATANA_ROUTE_CAPTURE_RATE_LIMIT:-20}"

katana_args=(
    -u "$RUNTIME_ROUTE_URL"
    -kf all
    -iqp
    -fsu
    -ns
    -s "$KATANA_STRATEGY"
    -d "$KATANA_ROUTE_CAPTURE_DEPTH"
    -ct "$KATANA_ROUTE_CAPTURE_DURATION"
    -timeout "$KATANA_ROUTE_CAPTURE_TIMEOUT_SECONDS"
    -time-stable "$KATANA_ROUTE_CAPTURE_TIME_STABLE_SECONDS"
    -retry "$KATANA_ROUTE_CAPTURE_RETRY_COUNT"
    -mfc "$KATANA_ROUTE_CAPTURE_MAX_FAILURE_COUNT"
    -c "$KATANA_ROUTE_CAPTURE_CONCURRENCY"
    -p "$KATANA_ROUTE_CAPTURE_PARALLELISM"
    -rl "$KATANA_ROUTE_CAPTURE_RATE_LIMIT"
    -mrs 16777216
    -omit-raw
    -omit-body
    -jsonl
    -silent
)
if [[ "${KATANA_ENABLE_HYBRID}" == "1" ]]; then
    katana_args+=(-hh -jc -fx -td -tlsi -duc)
fi
if [[ "${KATANA_ENABLE_XHR}" == "1" ]]; then
    katana_args+=(-xhr -xhr-extraction)
fi
if [[ "${KATANA_ENABLE_HEADLESS}" == "1" ]]; then
    if [[ "${KATANA_ENABLE_HYBRID}" != "1" ]]; then
        katana_args+=(-hl)
    fi
    katana_args+=(
        -system-chrome
        -system-chrome-path "$KATANA_CHROME_BIN"
        -headless-options "$KATANA_HEADLESS_OPTIONS"
    )
fi
if [[ "${KATANA_ENABLE_JSLUICE}" == "1" ]]; then
    katana_args+=(-jsl)
fi
if [[ "${KATANA_ENABLE_PATH_CLIMB}" == "1" ]]; then
    katana_args+=(-pc)
fi
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    katana_args+=(-cos "$line")
done < <(katana_emit_out_of_scope_regexes)

auth_args=()
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    auth_args+=("$line")
done < <(_auth_header_array)

scope_args=()
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    scope_args+=("$line")
done < <(_katana_scope_array)

if [[ "$(runtime_mode)" == "local" ]]; then
    "$KATANA_LOCAL_BIN" \
        "${katana_args[@]}" \
        "${scope_args[@]+${scope_args[@]}}" \
        "${auth_args[@]+${auth_args[@]}}" \
        -elog "$ERR_OUT" \
        -o "$TMP_OUT" \
        >/dev/null
else
    tmp_out_mount="/engagement/scans/route-captures/.${SLUG}.tmp.jsonl"
    err_out_mount="/engagement/scans/route-captures/${SLUG}.error.log"
    docker run --rm \
        --network host \
        -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
        "$KATANA_IMAGE" \
        "${katana_args[@]}" \
        "${scope_args[@]+${scope_args[@]}}" \
        "${auth_args[@]+${auth_args[@]}}" \
        -elog "$err_out_mount" \
        -o "$tmp_out_mount" \
        >/dev/null
fi

mv "$TMP_OUT" "$RAW_OUT"

python3 - "$ROUTE_URL" "$RAW_OUT" "$SUMMARY_OUT" <<'PY'
import json, sys
from pathlib import Path

route_url = sys.argv[1]
out_path = Path(sys.argv[2])
summary_path = Path(sys.argv[3])
lines = []
if out_path.exists():
    for raw in out_path.read_text(encoding='utf-8').splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            lines.append(json.loads(raw))
        except Exception:
            continue
xhr = 0
endpoints = []
statuses = []
for row in lines:
    req = row.get('request') or {}
    resp = row.get('response') or {}
    endpoint = req.get('endpoint') or req.get('url')
    if endpoint:
        endpoints.append(endpoint)
    status = resp.get('status_code')
    if isinstance(status, int):
        statuses.append(status)
    xhr += len(resp.get('xhr_requests') or [])
summary = {
    'route_url': route_url,
    'captures': len(lines),
    'xhr_requests': xhr,
    'unique_endpoints': sorted(dict.fromkeys(endpoints))[:20],
    'statuses': statuses[:20],
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
PY

echo "$RAW_OUT"
echo "$SUMMARY_OUT"
