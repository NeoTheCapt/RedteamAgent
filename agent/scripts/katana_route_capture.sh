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
TMP_OUT_PRIMARY="$OUT_DIR/.${SLUG}.primary.tmp.jsonl"
TMP_ERR_PRIMARY="$OUT_DIR/.${SLUG}.primary.tmp.err"
TMP_OUT_FALLBACK="$OUT_DIR/.${SLUG}.fallback.tmp.jsonl"
TMP_ERR_FALLBACK="$OUT_DIR/.${SLUG}.fallback.tmp.err"
trap 'rm -f "$TMP_OUT_PRIMARY" "$TMP_ERR_PRIMARY" "$TMP_OUT_FALLBACK" "$TMP_ERR_FALLBACK"' EXIT
: > "$TMP_OUT_PRIMARY"
: > "$TMP_ERR_PRIMARY"
: > "$TMP_OUT_FALLBACK"
: > "$TMP_ERR_FALLBACK"
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

build_katana_args() {
    local enable_hybrid="$1"
    local enable_headless="$2"
    local enable_xhr="$3"
    local -a args=(
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

    if [[ "$enable_hybrid" == "1" ]]; then
        args+=(-hh -jc -fx -td -tlsi -duc)
    fi
    if [[ "$enable_xhr" == "1" ]]; then
        args+=(-xhr -xhr-extraction)
    fi
    if [[ "$enable_headless" == "1" ]]; then
        if [[ "$enable_hybrid" != "1" ]]; then
            args+=(-hl)
        fi
        args+=(
            -system-chrome
            -system-chrome-path "$KATANA_CHROME_BIN"
            -headless-options "$KATANA_HEADLESS_OPTIONS"
        )
    fi
    if [[ "${KATANA_ENABLE_JSLUICE}" == "1" ]]; then
        args+=(-jsl)
    fi
    if [[ "${KATANA_ENABLE_PATH_CLIMB}" == "1" ]]; then
        args+=(-pc)
    fi
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        args+=(-cos "$line")
    done < <(katana_emit_out_of_scope_regexes)

    printf '%s\n' "${args[@]}"
}

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

run_route_capture_attempt() {
    local enable_hybrid="$1"
    local enable_headless="$2"
    local enable_xhr="$3"
    local out_path="$4"
    local err_path="$5"
    local -a katana_args=()
    local item

    : > "$out_path"
    : > "$err_path"
    while IFS= read -r item; do
        [[ -n "$item" ]] || continue
        katana_args+=("$item")
    done < <(build_katana_args "$enable_hybrid" "$enable_headless" "$enable_xhr")

    if [[ "$(runtime_mode)" == "local" ]]; then
        "$KATANA_LOCAL_BIN" \
            "${katana_args[@]}" \
            "${scope_args[@]+${scope_args[@]}}" \
            "${auth_args[@]+${auth_args[@]}}" \
            -elog "$err_path" \
            -o "$out_path" \
            >/dev/null
    else
        local out_mount
        local err_mount
        out_mount="/engagement/scans/route-captures/$(basename "$out_path")"
        err_mount="/engagement/scans/route-captures/$(basename "$err_path")"
        docker run --rm \
            --network host \
            -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
            "$KATANA_IMAGE" \
            "${katana_args[@]}" \
            "${scope_args[@]+${scope_args[@]}}" \
            "${auth_args[@]+${auth_args[@]}}" \
            -elog "$err_mount" \
            -o "$out_mount" \
            >/dev/null
    fi
}

route_capture_needs_fallback() {
    local raw_path="$1"
    local runtime_route_url="$2"
    python3 - "$raw_path" "$runtime_route_url" <<'PY'
import json, sys
from pathlib import Path

raw_path = Path(sys.argv[1])
route_url = sys.argv[2]
if not raw_path.exists():
    raise SystemExit(0)

seed_error = 0
seed_success = 0
response_rows = 0
for raw in raw_path.read_text(encoding='utf-8').splitlines():
    raw = raw.strip()
    if not raw:
        continue
    try:
        row = json.loads(raw)
    except Exception:
        continue
    req = row.get('request') or {}
    resp = row.get('response') or {}
    endpoint = req.get('endpoint') or req.get('url')
    if isinstance(resp.get('status_code'), int):
        response_rows += 1
    if endpoint != route_url:
        continue
    if row.get('error'):
        seed_error += 1
    if isinstance(resp.get('status_code'), int):
        seed_success += 1

should_fallback = seed_error > 0 and seed_success == 0 and response_rows <= 1
print('1' if should_fallback else '0')
PY
}

FALLBACK_USED=0
run_route_capture_attempt "${KATANA_ENABLE_HYBRID}" "${KATANA_ENABLE_HEADLESS}" "${KATANA_ENABLE_XHR}" "$TMP_OUT_PRIMARY" "$TMP_ERR_PRIMARY"

if [[ "${KATANA_ENABLE_HYBRID}" == "1" && "${KATANA_ENABLE_HEADLESS}" == "1" ]]; then
    if [[ "$(route_capture_needs_fallback "$TMP_OUT_PRIMARY" "$RUNTIME_ROUTE_URL")" == "1" ]]; then
        FALLBACK_USED=1
        run_route_capture_attempt "0" "${KATANA_ENABLE_HEADLESS}" "${KATANA_ENABLE_XHR}" "$TMP_OUT_FALLBACK" "$TMP_ERR_FALLBACK"
    fi
fi

cat "$TMP_OUT_PRIMARY" > "$RAW_OUT"
if [[ "$FALLBACK_USED" == "1" ]]; then
    if [[ -s "$TMP_OUT_PRIMARY" && -s "$TMP_OUT_FALLBACK" ]]; then
        printf '\n' >> "$RAW_OUT"
    fi
    cat "$TMP_OUT_FALLBACK" >> "$RAW_OUT"
fi

{
    printf '[route-capture] primary mode: hybrid=%s headless=%s xhr=%s\n' "${KATANA_ENABLE_HYBRID}" "${KATANA_ENABLE_HEADLESS}" "${KATANA_ENABLE_XHR}"
    cat "$TMP_ERR_PRIMARY"
    if [[ "$FALLBACK_USED" == "1" ]]; then
        printf '\n[route-capture] fallback mode: hybrid=0 headless=%s xhr=%s\n' "${KATANA_ENABLE_HEADLESS}" "${KATANA_ENABLE_XHR}"
        cat "$TMP_ERR_FALLBACK"
    fi
} > "$ERR_OUT"

python3 - "$ROUTE_URL" "$RUNTIME_ROUTE_URL" "$RAW_OUT" "$SUMMARY_OUT" "$FALLBACK_USED" <<'PY'
import json, sys
from pathlib import Path

route_url = sys.argv[1]
runtime_route_url = sys.argv[2]
out_path = Path(sys.argv[3])
summary_path = Path(sys.argv[4])
fallback_used = sys.argv[5] == '1'
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
response_rows = 0
seed_error_rows = 0
seed_response_rows = 0
for row in lines:
    req = row.get('request') or {}
    resp = row.get('response') or {}
    endpoint = req.get('endpoint') or req.get('url')
    if endpoint:
        endpoints.append(endpoint)
    status = resp.get('status_code')
    if isinstance(status, int):
        statuses.append(status)
        response_rows += 1
    xhr += len(resp.get('xhr_requests') or [])
    if endpoint == runtime_route_url:
        if row.get('error'):
            seed_error_rows += 1
        if isinstance(status, int):
            seed_response_rows += 1
summary = {
    'route_url': route_url,
    'runtime_route_url': runtime_route_url,
    'captures': len(lines),
    'response_rows': response_rows,
    'seed_error_rows': seed_error_rows,
    'seed_response_rows': seed_response_rows,
    'fallback_used': fallback_used,
    'xhr_requests': xhr,
    'unique_endpoints': sorted(dict.fromkeys(endpoints))[:30],
    'statuses': statuses[:30],
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
PY

echo "$RAW_OUT"
echo "$SUMMARY_OUT"
