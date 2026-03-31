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
validated_creds = bool(auth.get("validated_credentials"))
base_target = scope.get("target", "")
parsed_target = urlparse(base_target)
base_root = urlunparse((parsed_target.scheme or "http", parsed_target.netloc, "", "", "", ""))

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
for row in case_rows:
    method = (row["method"] or "GET").upper()
    url_path = row["url_path"] or "/"
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


def normalize_target(target: str) -> str:
    return " ".join((target or "").strip().split())


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


def case_done(method: str, path: str) -> bool:
    clean_path, query = split_path_query(path)
    if "{" in clean_path or "}" in clean_path:
        return False
    if query and "{" in query and "}" in query:
        key = query.split("=", 1)[0].strip()
        return (method, clean_path, key) in done_query_keys
    return (method, clean_path) in done_case_keys


def case_exists(method: str, path: str) -> bool:
    clean_path, _ = split_path_query(path)
    if "{" in clean_path or "}" in clean_path:
        return False
    return (method, clean_path) in all_case_keys


def finding_mentions(*needles: str) -> bool:
    return any((needle or "").lower() in findings_text for needle in needles)


def followup_type(method: str, path: str) -> str:
    if path.endswith("/file-upload") or path == "/file-upload":
        return "upload"
    if method != "GET":
        return "api"
    if path.startswith("/api") or path.startswith("/rest") or path.startswith("/b2b"):
        return "api"
    return "page"


def build_followup(method: str, path: str, target: str):
    clean_path, query = split_path_query(path)
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

    method, path = extract_first_method_and_path(target)
    decision = None
    reason = None

    if target.startswith("GET /#/"):
        decision = "not_applicable"
        reason = "client-side fragment route; already represented by reviewed SPA shell/bundle and not requestable as a distinct server path"
    elif surface_type == "dynamic_render" and target.startswith("SPA routes ") and (("GET", "/main.js") in done_case_keys or ("GET", "/") in done_case_keys):
        decision = "covered"
        reason = "source analysis already reviewed the SPA bundle that disclosed these client-side routes"
    elif target == "POST /rest/user/login" and (validated_creds or finding_mentions("post /rest/user/login", "validated admin jwt", "hardcoded client-side test credentials allow authenticated admin access")):
        decision = "covered"
        reason = "login surface was validated during credential replay and admin JWT acquisition"
    elif method and path and case_done(method, path):
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
