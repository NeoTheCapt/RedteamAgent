#!/usr/bin/env python3
"""Emit a compact JSON summary for a local JS/CSS/HTML source artifact.

The helper is intentionally bounded so source-analysis can inspect large local assets
without dumping whole bundles into model context.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

MAX_HEAD_BYTES = 2_000_000
MAX_TAIL_BYTES = 512_000
DEFAULT_LIMIT = 20
TEXT_NULL_BYTE_RATIO = 0.002

FRAMEWORK_MARKERS = {
    "angular": re.compile(r"\b(?:angular|zone\.js|ng[A-Z][A-Za-z0-9_]*)\b", re.I),
    "react": re.compile(r"\b(?:react|jsx|useState|useEffect|react-router)\b", re.I),
    "vue": re.compile(r"\b(?:vue(?:\.router)?|pinia|nuxt)\b", re.I),
    "svelte": re.compile(r"\b(?:svelte|sveltekit)\b", re.I),
    "bootstrap": re.compile(r"\bbootstrap\b", re.I),
    "material": re.compile(r"\b(?:mat-|material|cdk-[a-z-]+)\b", re.I),
    "jquery": re.compile(r"\b(?:jquery|\$\.ajax|\$\.get|\$\.post)\b", re.I),
    "webpack": re.compile(r"\b(?:webpack|sourceMappingURL|__webpack_)\b", re.I),
}

PATH_PATTERNS = [
    re.compile(r"(?:https?://[^\s\"'`<>()]+)?/(?:api|rest|graphql|swagger|openapi|api-docs|admin|auth|user|users|profile|account|login|register|reset|forgot|verify|2fa|mfa|otp|order|orders|basket|cart|checkout|review|feedback|upload|download|file|ftp|b2b|wallet|payment|config|search|track|address|privacy|legal|terms)[^\s\"'`<>()]*", re.I),
    re.compile(r"(?:https?://[^\s\"'`<>()]+)?/#/[^\s\"'`<>()]+", re.I),
    re.compile(r"#/[A-Za-z0-9_./?=&%-]+"),
]

IMPORT_PATTERNS = [
    re.compile(r"@import\s+(?:url\()?['\"]?([^'\")\s]+)", re.I),
    re.compile(r"url\(\s*['\"]?([^'\")\s]+)"),
]

SOURCEMAP_PATTERN = re.compile(r"sourceMappingURL\s*=\s*([^\s*]+)")

SECRET_PATTERNS = [
    re.compile(r"(?P<name>api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|bearer)\s*[:=]\s*['\"](?P<value>[^'\"\n]{6,200})['\"]", re.I),
    re.compile(r"(?P<name>authorization)\s*[:=]\s*['\"](?P<value>Bearer\s+[^'\"\n]{6,200})['\"]", re.I),
]


def preview(value: str, width: int = 18) -> str:
    if len(value) <= width:
        return value
    keep = max(4, width // 2)
    return f"{value[:keep]}…{value[-keep:]}"


def dedupe_keep_order(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def read_bounded_bytes(path: Path) -> tuple[bytes, bool]:
    size = path.stat().st_size
    if size <= MAX_HEAD_BYTES + MAX_TAIL_BYTES:
        return path.read_bytes(), False

    with path.open("rb") as fh:
        head = fh.read(MAX_HEAD_BYTES)
        fh.seek(max(0, size - MAX_TAIL_BYTES))
        tail = fh.read(MAX_TAIL_BYTES)
    marker = b"\n/* source_artifact_summary truncated middle */\n"
    return head + marker + tail, True


def decode_text(data: bytes) -> tuple[str, bool]:
    null_ratio = (data.count(b"\x00") / max(1, len(data)))
    likely_binary = null_ratio > TEXT_NULL_BYTE_RATIO
    text = data.decode("utf-8", errors="ignore")
    return text, likely_binary


def compute_line_stats(text: str) -> tuple[int, float]:
    if not text:
        return 0, 0.0
    lines = text.splitlines() or [text]
    line_count = len(lines)
    avg_line_length = round(sum(len(line) for line in lines) / max(1, line_count), 2)
    return line_count, avg_line_length


def normalize_path_match(value: str) -> str | None:
    cleaned = value.strip().strip("\"'`()[]{}<>,;:")
    if not cleaned:
        return None
    lower = cleaned.lower()
    # Avoid reporting static assets as high-signal paths unless they are source maps.
    static_suffixes = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".pdf", ".css", ".js"
    )
    if lower.endswith(static_suffixes) and not lower.endswith(".map"):
        return None
    if cleaned.startswith("//"):
        return None
    return cleaned


def extract_paths(text: str, limit: int) -> list[str]:
    matches: list[str] = []
    for pattern in PATH_PATTERNS:
        matches.extend(m.group(0) for m in pattern.finditer(text))
    normalized = [normalize_path_match(m) for m in matches]
    return dedupe_keep_order([m for m in normalized if m], limit)


def extract_import_refs(text: str, limit: int) -> list[str]:
    hits: list[str] = []
    for pattern in IMPORT_PATTERNS:
        hits.extend(m.group(1).strip() for m in pattern.finditer(text))
    return dedupe_keep_order(hits, limit)


def extract_sourcemaps(text: str, limit: int) -> list[str]:
    hits = [m.group(1).strip() for m in SOURCEMAP_PATTERN.finditer(text)]
    return dedupe_keep_order(hits, limit)


def extract_secret_previews(text: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group("name")
            value = match.group("value")
            key = (name.lower(), value)
            if key in seen:
                continue
            seen.add(key)
            results.append({"name": name, "preview": preview(value)})
            if len(results) >= limit:
                return results
    return results


def detect_framework_markers(text: str, limit: int) -> list[str]:
    hits = [name for name, pattern in FRAMEWORK_MARKERS.items() if pattern.search(text)]
    return hits[:limit]


def likely_minified(path: Path, size: int, line_count: int, avg_line_length: float, text: str) -> bool:
    if path.suffix.lower() not in {".js", ".css", ".mjs", ".cjs"}:
        return False
    if size < 48_000:
        return False
    if line_count <= 250:
        return True
    if avg_line_length >= 280:
        return True
    newline_density = text.count("\n") / max(1, len(text))
    return newline_density < 0.002


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a local source artifact into compact JSON")
    parser.add_argument("path", help="local file path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="per-section result cap")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(json.dumps({"error": f"file not found: {path}"}))
        return 1

    size = path.stat().st_size
    data, truncated = read_bounded_bytes(path)
    text, binaryish = decode_text(data)
    line_count, avg_line_length = compute_line_stats(text)

    result = {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": size,
        "analysis_window_bytes": len(data),
        "truncated_middle": truncated,
        "line_count": line_count,
        "avg_line_length": avg_line_length,
        "likely_binary": binaryish,
        "likely_minified": likely_minified(path, size, line_count, avg_line_length, text),
        "framework_markers": detect_framework_markers(text, args.limit),
        "high_signal_paths": extract_paths(text, args.limit),
        "import_refs": extract_import_refs(text, args.limit),
        "source_map_refs": extract_sourcemaps(text, args.limit),
        "secret_previews": extract_secret_previews(text, args.limit),
        "notes": [],
    }

    if truncated:
        result["notes"].append("summary scanned bounded head/tail windows instead of the full file")
    if result["likely_minified"]:
        result["notes"].append("large/minified asset: prefer targeted follow-up searches over whole-file reads")
    if binaryish:
        result["notes"].append("artifact contains null-byte density consistent with binary/non-text content")
    if not result["high_signal_paths"] and not result["secret_previews"] and result["framework_markers"]:
        result["notes"].append("framework/library markers present without obvious high-signal app routes or secrets")

    print(json.dumps(result, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
