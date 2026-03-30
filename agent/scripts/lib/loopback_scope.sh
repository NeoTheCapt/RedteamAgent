#!/usr/bin/env bash

normalize_target_for_scope() {
    local eng_dir="${1:-}"
    local target_spec="${2:-}"

    [[ -n "$target_spec" ]] || {
        printf '%s\n' "$target_spec"
        return 0
    }

    python3 - <<'PY' "$eng_dir" "$target_spec"
import json
import sys
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

eng_dir = Path(sys.argv[1])
target_spec = sys.argv[2]
scope_path = eng_dir / "scope.json"

if not scope_path.exists():
    print(target_spec)
    raise SystemExit(0)

try:
    scope_payload = json.loads(scope_path.read_text(encoding="utf-8"))
except Exception:
    print(target_spec)
    raise SystemExit(0)

scope_target = str((scope_payload or {}).get("target") or "").strip()
if not scope_target:
    print(target_spec)
    raise SystemExit(0)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal"}


def host_key(value: str | None) -> str:
    return (value or "").strip().lower().strip("[]")


def default_port(parsed: SplitResult) -> int | None:
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def split_target_spec(value: str) -> tuple[str, str]:
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].isalpha() and parts[1].startswith(("http://", "https://")):
        return parts[0].upper(), parts[1]
    if value.startswith(("http://", "https://")):
        return "", value
    return "", ""

scope_parsed = urlsplit(scope_target)
scope_host = host_key(scope_parsed.hostname)
if scope_parsed.scheme not in {"http", "https"} or scope_host not in LOOPBACK_HOSTS:
    print(target_spec)
    raise SystemExit(0)

method_prefix, candidate_url = split_target_spec(target_spec)
if not candidate_url:
    print(target_spec)
    raise SystemExit(0)

candidate_parsed = urlsplit(candidate_url)
candidate_host = host_key(candidate_parsed.hostname)
if candidate_parsed.scheme not in {"http", "https"} or candidate_host not in LOOPBACK_HOSTS:
    print(target_spec)
    raise SystemExit(0)

scope_port = default_port(scope_parsed)
candidate_port = default_port(candidate_parsed)
if candidate_parsed.scheme == scope_parsed.scheme and candidate_port == scope_port:
    rewritten = urlunsplit((
        scope_parsed.scheme,
        scope_parsed.netloc,
        candidate_parsed.path or "/",
        candidate_parsed.query,
        candidate_parsed.fragment,
    ))
    if method_prefix:
        print(f"{method_prefix} {rewritten}")
    else:
        print(rewritten)
    raise SystemExit(0)

raise SystemExit(10)
PY
}
