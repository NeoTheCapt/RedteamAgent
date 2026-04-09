#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: reconcile_surface_coverage.sh <engagement_dir> [--ingest-followups]}"
INGEST_FOLLOWUPS="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPEND_SURFACE_JSONL="$SCRIPT_DIR/append_surface_jsonl.sh"
RECON_INGEST="$SCRIPT_DIR/recon_ingest.sh"

[[ -d "$ENG_DIR" ]] || {
    echo "engagement dir not found: $ENG_DIR" >&2
    exit 1
}

updates_tmp="$(mktemp "${TMPDIR:-/tmp}/surface-updates.XXXXXX.jsonl")"
followups_tmp="$(mktemp "${TMPDIR:-/tmp}/surface-followups.XXXXXX.jsonl")"
report_tmp="$(mktemp "${TMPDIR:-/tmp}/surface-report.XXXXXX.txt")"
trap 'rm -f "$updates_tmp" "$followups_tmp" "$report_tmp"' EXIT

python3 - "$ENG_DIR" "$updates_tmp" "$followups_tmp" >"$report_tmp" <<'PY'
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote

eng_dir = Path(sys.argv[1])
updates_path = Path(sys.argv[2])
followups_path = Path(sys.argv[3])

scope = json.loads((eng_dir / "scope.json").read_text())
surfaces_file = eng_dir / "surfaces.jsonl"
findings_text = (eng_dir / "findings.md").read_text(encoding="utf-8").lower() if (eng_dir / "findings.md").exists() else ""
auth = json.loads((eng_dir / "auth.json").read_text()) if (eng_dir / "auth.json").exists() else {}
legacy_credentials = auth.get("credentials") if isinstance(auth.get("credentials"), list) else []
validated_creds = bool(auth.get("validated_credentials") or legacy_credentials)
base_target = scope.get("target", "")
parsed_target = urlparse(base_target)
base_root = urlunparse((parsed_target.scheme or "http", parsed_target.netloc, "", "", "", ""))
allowed_scope_entries = []
for item in [scope.get("hostname"), *(scope.get("scope") or [])]:
    item = str(item or "").strip().lower()
    if item:
        allowed_scope_entries.append(item)
allowed_scope_entries = sorted(set(allowed_scope_entries))

rows = []
if surfaces_file.exists():
    for raw in surfaces_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        rows.append(json.loads(raw))

conn = sqlite3.connect(str(eng_dir / "cases.db"))
conn.row_factory = sqlite3.Row
case_rows = conn.execute(
    "select method, url, url_path, query_params, type, status from cases"
).fetchall()
conn.close()

all_case_keys = set()
done_case_keys = set()
done_paths = set()
done_query_keys = set()
known_locale_prefixes = []
seen_locale_prefixes = set()


def remember_locale_prefix(url_path: str | None):
    value = str(url_path or "").strip()
    match = re.match(r"^/([a-z]{2}(?:[-_][a-z]{2})?)(?:/|$)", value, re.IGNORECASE)
    if not match:
        return
    prefix = f"/{match.group(1).lower()}"
    if prefix not in seen_locale_prefixes:
        seen_locale_prefixes.add(prefix)
        known_locale_prefixes.append(prefix)


for row in case_rows:
    method = (row["method"] or "GET").upper()
    url_path = row["url_path"] or "/"
    remember_locale_prefix(url_path)
    query_raw = row["query_params"] or "{}"
    try:
        query_obj = json.loads(query_raw)
    except Exception:
        query_obj = {}
    case_key = (method, url_path)
    all_case_keys.add(case_key)
    if row["status"] == "done":
        done_case_keys.add(case_key)
        done_paths.add(url_path)
        for key in query_obj.keys():
            done_query_keys.add((method, url_path, str(key)))

for row in rows:
    target = " ".join(str(row.get("target") or "").strip().split())
    if not target:
        continue
    if target.startswith(("GET /", "POST /", "PUT /", "DELETE /", "PATCH /", "HEAD /", "OPTIONS /")):
        _, surface_path = target.split(" ", 1)
        remember_locale_prefix(surface_path)
    elif "://" in target and target.startswith(("GET ", "POST ", "PUT ", "DELETE ", "PATCH ", "HEAD ", "OPTIONS ")):
        _, absolute_target = target.split(" ", 1)
        remember_locale_prefix(urlparse(absolute_target).path)


def normalize_target(target: str) -> str:
    return " ".join((target or "").strip().split())


def normalize_request_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        value = "/" + value.lstrip("/")
    return value


def candidate_paths(path: str, locale_scoped: bool = False):
    clean_path, query = split_path_query(path)
    clean_path = normalize_request_path(clean_path)
    candidates = []
    if locale_scoped:
        for prefix in known_locale_prefixes:
            if clean_path == "/":
                candidate = prefix
            else:
                candidate = f"{prefix}{clean_path}"
            candidates.append(candidate)
    candidates.append(clean_path)
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(f"{candidate}?{query}" if query else candidate)
    return deduped


def extract_first_method_and_path(target: str):
    target = normalize_target(target)
    if not target:
        return None, None
    if target.startswith("SPA routes "):
        return "GET", "/"
    if "://" in target and target.startswith(("GET ", "POST ", "PUT ", "DELETE ", "PATCH ", "HEAD ", "OPTIONS ")):
        method, rest = target.split(" ", 1)
        parsed = urlparse(rest)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return method.upper(), path
    parts = target.split(" ", 1)
    if len(parts) != 2:
        return None, None
    method_token, path = parts
    methods = [m for m in method_token.split("|") if m]
    method = methods[0].upper() if methods else None
    return method, path


def split_path_query(path: str):
    if not path:
        return "", ""
    if "?" not in path:
        return path, ""
    left, right = path.split("?", 1)
    return left, right


def case_done(method: str, path: str, locale_scoped: bool = False) -> bool:
    for candidate in candidate_paths(path, locale_scoped=locale_scoped):
        clean_path, query = split_path_query(candidate)
        if "{" in clean_path or "}" in clean_path:
            continue
        if query and "{" in query and "}" in query:
            key = query.split("=", 1)[0].strip()
            if (method, clean_path, key) in done_query_keys:
                return True
            continue
        if (method, clean_path) in done_case_keys:
            return True
    return False


def case_exists(method: str, path: str, locale_scoped: bool = False) -> bool:
    for candidate in candidate_paths(path, locale_scoped=locale_scoped):
        clean_path, _ = split_path_query(candidate)
        if "{" in clean_path or "}" in clean_path:
            continue
        if (method, clean_path) in all_case_keys:
            return True
    return False


def first_missing_candidate_path(method: str, path: str, locale_scoped: bool = False) -> str:
    candidates = candidate_paths(path, locale_scoped=locale_scoped)
    for candidate in candidates:
        if not case_exists(method, candidate):
            return candidate
    return candidates[0]


def host_in_scope(host: str | None) -> bool:
    value = (host or "").strip().lower().strip("[]")
    if not value:
        return False
    if value in {"127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal"}:
        return True
    for allowed in allowed_scope_entries:
        if value == allowed:
            return True
        if allowed.startswith("*."):
            wildcard = allowed[2:]
            if value == wildcard or value.endswith(f".{wildcard}"):
                return True
    return False


def parse_target_request(target: str):
    target = normalize_target(target)
    if not target:
        return None, None, None, None, False
    parts = target.split(" ", 1)
    if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        method = parts[0].upper()
        rest = parts[1].strip()
    else:
        method = None
        rest = target

    locale_scoped = False
    if rest.startswith("locale-scoped "):
        locale_scoped = True
        rest = rest[len("locale-scoped "):].strip()

    if rest.startswith(("http://", "https://")):
        parsed = urlparse(rest)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return method or "GET", path, rest, (parsed.hostname or "").lower(), locale_scoped

    if method:
        return method, rest, None, None, locale_scoped

    return None, None, None, None, locale_scoped


def target_is_nonrequestable(target: str, path: str | None) -> bool:
    value = normalize_target(target)
    check = f"{value} {path or ''}".lower()
    markers = [
        "...",
        "<",
        ">",
        "{",
        "}",
        " -> ",
        " and ",
        " or ",
        " | ",
        "client cookie names:",
        "frontend routes ",
        "spa routes ",
    ]
    if any(marker in check for marker in markers):
        return True
    if "*" in (path or "") or "*" in value:
        return True
    return False


def finding_mentions(*needles: str) -> bool:
    return any((needle or "").lower() in findings_text for needle in needles)


def followup_type(method: str, path: str) -> str:
    if path.endswith("/file-upload") or path == "/file-upload":
        return "upload"
    if method != "GET":
        return "api"
    api_prefixes = (
        "/api",
        "/rest",
        "/b2b",
        "/priapi",
        "/v1/",
        "/v2/",
        "/v3/",
        "/v4/",
        "/v5/",
        "/v6/",
    )
    if path.startswith(api_prefixes):
        return "api"
    return "page"


def build_followup(method: str, path: str, target: str, absolute_url: str | None = None):
    clean_path, query = split_path_query(path)
    clean_path = normalize_request_path(clean_path)
    if absolute_url:
        parsed = urlparse(absolute_url)
        full_url = urlunparse((parsed.scheme, parsed.netloc, clean_path, "", query, ""))
    else:
        full_url = f"{base_root}{clean_path}"
        if query:
            full_url = f"{full_url}?{query}"
    item = {
        "method": method,
        "url": full_url,
        "url_path": clean_path,
        "type": followup_type(method, clean_path),
        "source": "operator-surface-coverage",
        "notes": f"surface coverage follow-up for {target}",
    }
    if query:
        query_obj = {}
        key, _, value = query.partition("=")
        query_obj[key] = value
        item["query_params"] = query_obj
    return item


updates = []
followups = []
remaining = []
seen_followups = set()

for row in rows:
    target = normalize_target(str(row.get("target") or ""))
    status = str(row.get("status") or "discovered").strip().lower()
    surface_type = str(row.get("surface_type") or "").strip().lower()
    if status != "discovered" or not target:
        continue

    method, path, absolute_url, absolute_host, locale_scoped = parse_target_request(target)
    decision = None
    reason = None

    if target.startswith("GET /#/"):
        decision = "not_applicable"
        reason = "client-side fragment route; already represented by reviewed SPA shell/bundle and not requestable as a distinct server path"
    elif surface_type == "dynamic_render" and target.startswith("SPA routes ") and (("GET", "/main.js") in done_case_keys or ("GET", "/") in done_case_keys):
        decision = "covered"
        reason = "source analysis already reviewed the SPA bundle that disclosed these client-side routes"
    elif absolute_host and not host_in_scope(absolute_host):
        decision = "not_applicable"
        reason = f"surface references out-of-scope host {absolute_host}"
    elif not method or not path:
        decision = "not_applicable"
        reason = "surface is advisory metadata without a concrete requestable target"
    elif target_is_nonrequestable(target, path):
        decision = "not_applicable"
        reason = "surface target is abstract or multi-step and cannot be exercised as one bounded request"
    elif target == "POST /rest/user/login" and (validated_creds or finding_mentions("post /rest/user/login", "validated admin jwt", "hardcoded client-side test credentials allow authenticated admin access")):
        decision = "covered"
        reason = "login surface was validated during credential replay and admin JWT acquisition"
    elif method and path and case_done(method, path, locale_scoped=locale_scoped):
        decision = "covered"
        reason = "matching representative case already completed in the queue"
    elif target == "GET /rest/user/security-question?email={email}" and case_done("GET", "/rest/user/security-question?email="):
        decision = "covered"
        reason = "security-question endpoint was already exercised as a bounded coverage check"
    elif target == "GET /rest/admin/application-version" and finding_mentions("/rest/admin/application-version"):
        decision = "covered"
        reason = "admin application-version endpoint is already covered by recorded findings and completed API triage"
    elif target == "GET /rest/repeat-notification" and (case_done("GET", "/rest/repeat-notification") or finding_mentions("/rest/repeat-notification")):
        decision = "covered"
        reason = "repeat-notification endpoint was already exercised during bounded API triage"

    if decision:
        updates.append({
            "surface_type": surface_type,
            "target": target,
            "source": "operator-surface-coverage",
            "rationale": reason,
            "evidence_ref": "scans/surface-coverage-followups.jsonl" if decision == "covered" else "scope.json",
            "status": decision,
        })
        continue

    if method and path and not case_exists(method, path, locale_scoped=locale_scoped):
        followup_path = first_missing_candidate_path(method, path, locale_scoped=locale_scoped)
        if (method, followup_path) not in seen_followups:
            followups.append(build_followup(method, followup_path, target, absolute_url if not locale_scoped else None))
            seen_followups.add((method, followup_path))
        remaining.append(f"{surface_type} | {target}")
        continue

    candidate_followups = {
        "GET /profile": ("GET", "/profile"),
        "POST /rest/user/reset-password": ("POST", "/rest/user/reset-password"),
        "POST /rest/2fa/setup": ("POST", "/rest/2fa/setup"),
        "POST /rest/2fa/verify": ("POST", "/rest/2fa/verify"),
        "POST /file-upload": ("POST", "/file-upload"),
        "POST /rest/2fa/disable": ("POST", "/rest/2fa/disable"),
        "POST /rest/user/erasure-request": ("POST", "/rest/user/erasure-request"),
        "POST /rest/user/data-export": ("POST", "/rest/user/data-export"),
        "POST /api/Addresss/": ("POST", "/api/Addresss/"),
    }

    followup_spec = candidate_followups.get(target)
    if followup_spec:
        f_method, f_path = followup_spec
        if not case_exists(f_method, f_path) and (f_method, f_path) not in seen_followups:
            followups.append(build_followup(f_method, f_path, target))
            seen_followups.add((f_method, f_path))
        remaining.append(f"{surface_type} | {target}")
        continue

    remaining.append(f"{surface_type} | {target}")

with updates_path.open("w", encoding="utf-8") as fh:
    for row in updates:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")

with followups_path.open("w", encoding="utf-8") as fh:
    for row in followups:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")

print(f"surface coverage reconciliation: auto-resolved {len(updates)} surface(s)")
print(f"surface coverage reconciliation: queued {len(followups)} concrete follow-up case(s)")
if remaining:
    print("surface coverage reconciliation: remaining unresolved surfaces")
    for item in remaining:
        print(f"  - {item}")
else:
    print("surface coverage reconciliation: no unresolved discovered surfaces remain")
PY

if [[ -s "$updates_tmp" ]]; then
    "$APPEND_SURFACE_JSONL" "$ENG_DIR" < "$updates_tmp"
fi

mkdir -p "$ENG_DIR/scans"
if [[ -s "$followups_tmp" ]]; then
    cp "$followups_tmp" "$ENG_DIR/scans/surface-coverage-followups.jsonl"
else
    : > "$ENG_DIR/scans/surface-coverage-followups.jsonl"
fi

if [[ "$INGEST_FOLLOWUPS" == "--ingest-followups" && -s "$followups_tmp" ]]; then
    "$RECON_INGEST" "$ENG_DIR/cases.db" operator-surface-coverage < "$followups_tmp"
fi

cat "$report_tmp"
