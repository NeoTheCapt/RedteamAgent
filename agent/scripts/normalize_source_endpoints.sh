#!/usr/bin/env bash
set -euo pipefail

python3 /dev/fd/3 3<<'PY'
import json
import re
import sys
from urllib.parse import urlparse

ALLOWED_TYPES = {
    "api",
    "api-spec",
    "form",
    "upload",
    "graphql",
    "websocket",
    "page",
    "javascript",
    "stylesheet",
    "data",
}

TEMPLATE_RE = re.compile(
    r"(\{\{|\}\}|"
    r"\{[A-Za-z0-9_-]+\}|"
    r":[A-Za-z_][A-Za-z0-9_-]*\b|"
    r"'\+|\"\+|"
    r"%7B%7B|%7D%7D)",
    re.IGNORECASE,
)

NOISE_SEGMENTS = (
    "application/vnd.",
    "text/",
    "audio/",
    "video/",
    "image/",
    "font/",
)

NOISE_PATHS = {
    "/-",
    "/edge/",
    "/trident/",
    "/meta",
    "/index",
}


def reject(reason: str, raw: str) -> None:
    print(f"[normalize_source_endpoints] drop: {reason}: {raw}", file=sys.stderr)


for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue

    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        reject("non-json line", line)
        continue

    if not isinstance(row, dict):
        reject("json value is not an object", line)
        continue

    method = str(row.get("method", "")).upper()
    url = str(row.get("url", ""))
    url_path = str(row.get("url_path", ""))
    case_type = str(row.get("type", ""))

    if not method or not url or not url_path or not case_type:
        reject("missing required fields", line)
        continue

    if case_type not in ALLOWED_TYPES:
        reject(f"unsupported type {case_type}", line)
        continue

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        reject("url is not absolute http(s)", line)
        continue

    if not url_path.startswith("/"):
        reject("url_path is not absolute", line)
        continue

    if parsed.path != url_path:
        reject("url_path does not match url path", line)
        continue

    url_path_lower = url_path.lower()
    if any(url_path_lower.lstrip("/").startswith(prefix) for prefix in NOISE_SEGMENTS):
        reject("looks like mime string, not endpoint", line)
        continue

    if url_path_lower in NOISE_PATHS:
        reject("known noise path", line)
        continue

    if TEMPLATE_RE.search(url) or TEMPLATE_RE.search(url_path):
        reject("templated or unresolved dynamic endpoint", line)
        continue

    if any(ch in url_path for ch in (" ", "\t", "\n", "\r")):
        reject("whitespace in path", line)
        continue

    print(json.dumps(row, separators=(",", ":")))
PY
