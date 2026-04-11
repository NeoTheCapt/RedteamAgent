#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/surfaces.sh"

ENG_DIR="${1:?usage: check_surface_coverage.sh <engagement_dir>}"
SURFACE_FILE="$(surface_file_path "$ENG_DIR")"

[[ -f "$SURFACE_FILE" ]] || { echo "surfaces.jsonl not found in $ENG_DIR" >&2; exit 1; }

out="$(python3 - <<'PY' "$ENG_DIR" "$SURFACE_FILE"
import json
import sys
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

eng_dir = Path(sys.argv[1])
path = Path(sys.argv[2])
strict_deferred_types = {
    "account_recovery",
    "dynamic_render",
    "object_reference",
    "privileged_write",
}
status_rank = {
    "discovered": 0,
    "deferred": 1,
    "not_applicable": 2,
    "covered": 3,
}
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal"}

scope_target = ""
scope_path = eng_dir / "scope.json"
if scope_path.exists():
    try:
        scope_payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except Exception:
        scope_payload = {}
    scope_target = str((scope_payload or {}).get("target") or "").strip()

scope_parsed = urlsplit(scope_target) if scope_target else None
scope_host = (scope_parsed.hostname or "").strip().lower().strip("[]") if scope_parsed else ""


def default_port(parsed: SplitResult) -> int | None:
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def normalize_fragment_path(value: str) -> str:
    fragment = value.strip()
    if fragment.startswith("/#/"):
        return fragment
    if fragment.startswith("#/"):
        return "/" + fragment
    if fragment.startswith("/"):
        return "/#" + fragment
    return "/#/" + fragment.lstrip("#/")


def split_target_spec(value: str):
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in METHODS:
        return parts[0].upper(), parts[1].strip()
    return None, value


def canonicalize_target(value: str) -> str:
    value = " ".join(str(value or "").strip().split())
    if not value:
        return value
    method, remainder = split_target_spec(value)
    if remainder.startswith(("http://", "https://")):
        parsed = urlsplit(remainder)
        candidate_host = (parsed.hostname or "").strip().lower().strip("[]")
        candidate_port = default_port(parsed)
        scope_port = default_port(scope_parsed) if scope_parsed else None
        same_scope_host = bool(
            scope_parsed
            and parsed.scheme == scope_parsed.scheme
            and candidate_port == scope_port
            and (
                candidate_host == scope_host
                or (candidate_host in LOOPBACK_HOSTS and scope_host in LOOPBACK_HOSTS)
            )
        )
        if same_scope_host:
            if parsed.fragment:
                normalized_path = normalize_fragment_path(parsed.fragment)
            else:
                normalized_path = parsed.path or "/"
                if parsed.query:
                    normalized_path = f"{normalized_path}?{parsed.query}"
            return f"{method or 'GET'} {normalized_path}"
        return f"{method + ' ' if method else ''}{remainder}"
    if remainder.startswith(("/#/", "#/")):
        return f"{method or 'GET'} {normalize_fragment_path(remainder)}"
    if remainder.startswith("/"):
        return f"{method or 'GET'} {remainder}"
    return f"{method + ' ' if method else ''}{remainder}"


aggregated = {}
with path.open("r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        surface_type = row.get("surface_type")
        target = row.get("target")
        status = str(row.get("status") or "discovered").strip().lower()
        key = (surface_type, canonicalize_target(str(target or "")))
        current = aggregated.get(key)
        if current is None or status_rank.get(status, -1) >= status_rank.get(current["status"], -1):
            aggregated[key] = {"surface_type": surface_type, "target": target, "status": status}

unresolved = []
blocked_deferred = []
for row in aggregated.values():
    surface_type = row["surface_type"]
    target = row["target"]
    status = row["status"]
    if status == "discovered":
        unresolved.append(f'{surface_type} | {target}')
    elif status == "deferred" and surface_type in strict_deferred_types:
        blocked_deferred.append(f'{surface_type} | {target}')

if unresolved or blocked_deferred:
    if unresolved:
        print("Uncovered surfaces remain:")
        for item in unresolved:
            print(f"  - {item}")
    if blocked_deferred:
        print("High-risk surfaces cannot remain deferred:")
        for item in blocked_deferred:
            print(f"  - {item}")
        print("Resolve them as covered or not_applicable before finishing Test/Report.")
    sys.exit(1)
print("surface coverage: ok")
PY
)" || {
    printf '%s\n' "$out" >&2
    exit 1
}

printf '%s\n' "$out"
