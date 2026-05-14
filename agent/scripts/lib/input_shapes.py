#!/usr/bin/env python3
"""Generic input-shape classifier for cases.db case payloads.

Vulnerability-analyst's probe budget is tight (1-2 probes per family). When
SSRF/SSTI/XXE/NoSQL families are described as a buffet, structurally
vulnerable surfaces are missed because the agent runs out of budget on
high-volume families (SQLi/XSS) before reaching the structural ones. This
classifier emits input-SHAPE tags (not target-specific paths) so
vulnerability-analyst can make the matching probe families MANDATORY when
the input shape demands them.

Tags + bound probe families (kept in sync with vulnerability-analyst.txt):

    url_input         -> SSRF probe (localhost / metadata host / file scheme)
    xml_input         -> XXE probe (external entity / DOCTYPE)
    template_renderer -> SSTi probe ({{7*7}}, ${7*7})
    json_writer       -> NoSQL operator probe / mass-assignment role injection
    image_loader      -> cross-site image / SSRF-via-image fetch

Generality contract (do NOT break):

  * No url_path substring matches a specific endpoint name from any target.
  * No param VALUE matches a specific token from any target.
  * Param NAME patterns are generic SSRF-prone names that appear in every
    web framework's docs (url, redirect, callback, webhook, ...). Adding a
    target-specific name here is a contract violation.
  * Heuristics use input SHAPE (content-type, method, body structure,
    param name shape) and never query the target.

Usage:

    # Stdin -> stdout (single case)
    echo '<case-json>' | input_shapes.py

    # In-place on a batch array (the fetch_batch_to_file.sh wiring)
    input_shapes.py --batch <batch-json-file>

Output: when invoked --batch, adds an "input_shapes": [...] array to each
case object in place. When invoked stdin->stdout, emits the same object
with the field added. The field is sorted/deduped and may be empty [].
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


# Import case_utils via spec-load so this module stays runnable from any
# cwd (the unit tests load each classifier in isolation). Path is fixed
# relative to this file.
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("case_utils", _HERE / "case_utils.py")
case_utils = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(case_utils)  # type: ignore[union-attr]
_decode_params_shared = case_utils.decode_params

# Generic SSRF-prone parameter token vocabulary. Real SPAs commonly carry
# prefixed/compound names (`user_url`, `avatar_url`, `redirectUrl`,
# `webhook_callback`), so we match against TOKENIZED forms — split the
# param name on snake_case / kebab-case / camelCase boundaries, lowercase,
# and check whether any resulting token is in our vocabulary. Substring
# false-positives are avoided because we compare against discrete tokens,
# not raw substrings.
_SSRF_TOKENS = frozenset({
    "url", "uri", "src", "source", "target", "dest", "destination",
    "callback", "return", "returnto", "returnurl",
    "redirect", "redirectto", "redirecturl", "redirecturi",
    "next", "continue", "forward", "forwardto",
    "origin", "fetch", "fetchfrom", "proxy", "webhook", "webhookurl",
    "image", "imageurl", "avatar", "avatarurl",
    "thumbnail", "thumbnailurl", "fileurl", "link", "href", "location",
})

# Insert a delimiter before any capital that follows a lowercase letter,
# so `redirectUrl` tokenizes to `redirect`, `Url` — both lowercase-folded
# to `redirect`, `url`.
_CAMEL_SPLIT = re.compile(r"([a-z0-9])([A-Z])")


def _is_ssrf_param_name(name: str) -> bool:
    if not name:
        return False
    snake = _CAMEL_SPLIT.sub(r"\1_\2", name).lower()
    return any(t for t in re.split(r"[_\-\s.]+", snake) if t in _SSRF_TOKENS)

# A param VALUE that is itself a URL also signals url_input. Covers
# absolute http(s) and protocol-relative.
_URL_VALUE = re.compile(r"^\s*(?:https?:|//)", re.IGNORECASE)

# Unrendered template-engine markers. Post-M6 fix: dropped two
# patterns that collided with JS / FreeMarker syntax common in JS
# bundles:
#   * `${...}` matches ES6 template literals (every modern JS bundle
#     has `${variable}` strings reflected back to clients)
#   * `<#...>` matches FreeMarker but also any HTML tag whose first
#     character is `#` (rare but possible in some doc layouts)
# Kept the two unambiguous server-template-engine markers: Jinja /
# Twig / Handlebars `{{...}}` and ERB / EJS `<%...%>`. Both signal a
# server-side template engine that didn't render its placeholders —
# a strong SSTi indicator regardless of framework.
_TEMPLATE_MARKER = re.compile(
    r"\{\{\s*[^{}\s][^{}]*\}\}"     # Jinja / Twig / Handlebars / Vue / Angular: {{ x }}
    r"|<%\s*[^%]+%>"                  # ERB / EJS: <% x %>
)

# url_path tokens that indicate an image consumer endpoint. Generic web-app
# vocabulary, not target-specific.
_IMAGE_CONSUMER_PATH = re.compile(
    r"(?i)(?:^|/)(?:image|images|img|photo|photos|avatar|avatars|"
    r"thumb|thumbnail|picture|preview|media|gallery|cover|banner)(?:/|\.|$)"
)

# XML body fingerprints. Either content-type advertises XML or the body
# begins with an XML preamble / DOCTYPE / single root element with namespace.
_XML_BODY_PREFIX = re.compile(r"^\s*(?:<\?xml|<!DOCTYPE\b|<[A-Za-z][^>]*\bxmlns=)", re.IGNORECASE)


# Use the shared param decoder so every classifier sees the same view
# of a case. See agent/scripts/lib/case_utils.py.
_decode_params = _decode_params_shared


def _all_param_pairs(case: dict) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for col in ("query_params", "body_params", "path_params", "cookie_params"):
        d = _decode_params(case.get(col))
        for k, v in d.items():
            pairs.append((str(k), v))
    return pairs


def classify(case: dict) -> list[str]:
    """Return sorted list of input-shape tags for one case payload."""
    shapes: set[str] = set()
    method = str(case.get("method") or "").upper()
    content_type = str(case.get("content_type") or "").lower()
    body = str(case.get("body") or "")
    snippet = str(case.get("response_snippet") or "")
    url_path = str(case.get("url_path") or case.get("url") or "")

    pairs = _all_param_pairs(case)

    # url_input: any SSRF-style param name OR any string value that looks
    # like a URL. Either signal is enough — both are necessary for coverage
    # on opaque APIs that name params generically (e.g. "q", "src") but
    # carry a URL in the value.
    for name, value in pairs:
        if _is_ssrf_param_name(name):
            shapes.add("url_input")
            break
        if isinstance(value, str) and _URL_VALUE.match(value):
            shapes.add("url_input")
            break

    # xml_input: content-type advertises XML OR body begins with XML
    # preamble/DOCTYPE/namespaced root element.
    if "xml" in content_type or _XML_BODY_PREFIX.match(body):
        shapes.add("xml_input")

    # template_renderer: response or echoed request body contains unrendered
    # template markers. SSTi is worth probing wherever the server returns
    # template-language fingerprints, regardless of url_path.
    if _TEMPLATE_MARKER.search(snippet) or _TEMPLATE_MARKER.search(body):
        shapes.add("template_renderer")

    # json_writer: a JSON-bodied POST/PUT/PATCH with at least one body
    # parameter is the canonical NoSQL-operator-injection / mass-assignment
    # surface. The probe family is operator-injection (`{"$gt":""}`,
    # `{"$ne":""}`) plus role/admin field injection (mass assignment).
    if method in {"POST", "PUT", "PATCH"} and "json" in content_type:
        has_body_param = any(
            _decode_params(case.get(col)) for col in ("body_params", "query_params")
        )
        if has_body_param or body.strip().startswith("{"):
            shapes.add("json_writer")

    # image_loader: a url_input plus an image-consumer path is the cross-site
    # imaging primitive. Without url_input the image path is just a
    # static-content request, not a fetch-from-attacker surface.
    if "url_input" in shapes and _IMAGE_CONSUMER_PATH.search(url_path):
        shapes.add("image_loader")

    return sorted(shapes)


def _annotate_batch(path: Path) -> int:
    """Read a JSON array of cases, annotate each with input_shapes, write
    back in place. Returns the count of cases annotated."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, list):
        return 0
    annotated = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entry["input_shapes"] = classify(entry)
        annotated += 1
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return annotated


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--batch":
        path = Path(argv[2])
        count = _annotate_batch(path)
        # Print a compact summary for the operator. The fetch wrapper
        # extracts this as BATCH_INPUT_SHAPES.
        if count == 0:
            print("input_shapes_summary=empty")
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("input_shapes_summary=parse_error")
            return 0
        agg: dict[str, int] = {}
        for entry in payload:
            for tag in entry.get("input_shapes") or []:
                agg[tag] = agg.get(tag, 0) + 1
        if not agg:
            print("input_shapes_summary=none")
        else:
            print("input_shapes_summary=" + ",".join(
                f"{tag}:{count}" for tag, count in sorted(agg.items())
            ))
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        case = json.loads(raw)
    except ValueError as exc:
        print(f"input_shapes: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if isinstance(case, dict):
        case["input_shapes"] = classify(case)
        json.dump(case, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
