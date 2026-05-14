#!/usr/bin/env python3
"""Shared case-payload utilities used by every classifier in this
directory. Pre-M4 fix, three classifiers (input_shapes, surface_tags,
security_question) each carried their own copy of `_decode_params`,
and they had drifted out of sync — `input_shapes` handled list-form
params (e.g. `[["email","x"],["password","y"]]`) but `surface_tags`
did not, so the same case got different tags from different
classifiers.

Hoisting the helper into one module ensures every classifier sees
the same parsed view of a case. No target-specific logic here.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl


# A string that LOOKS like form-encoded params (`a=1&b=2` or `a=1`).
# Used as a fallback when JSON decode fails — some recon producers
# emit `body_params` / `query_params` as raw form-encoded text.
_FORM_LIKE = re.compile(r"^[A-Za-z_][\w\-.]*=[^&]*(?:&[A-Za-z_][\w\-.]*=[^&]*)*$")


def decode_params(raw: Any) -> dict:
    """Return a dict view of a case's query / body / path / cookie
    params. Tolerates every shape the producers emit:

      * dict — return as-is
      * list of [k, v] pairs — flatten to dict
      * JSON-encoded string — parse and recurse
      * form-encoded string (`a=1&b=2`) — parse via urllib (Codex-review)
      * bytes — decode as utf-8 and recurse
      * None / empty / unknown — return {}

    Never raises. Unknown shapes become {} so caller's downstream
    membership checks short-circuit on empty input.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        try:
            return decode_params(raw.decode("utf-8", errors="replace"))
        except Exception:
            return {}
    if isinstance(raw, list):
        out: dict = {}
        for entry in raw:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                out[str(entry[0])] = entry[1]
        return out
    if isinstance(raw, str):
        stripped = raw.strip()
        # JSON shape — prefer this when it parses cleanly. JSON `null`
        # decodes to None which short-circuits the recursion above.
        if stripped.startswith(("{", "[", '"')) or stripped in ("null", "true", "false"):
            try:
                parsed = json.loads(stripped)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return decode_params(parsed)
        # Form-encoded fallback for producers that store raw form data.
        if _FORM_LIKE.match(stripped):
            try:
                return dict(parse_qsl(stripped, keep_blank_values=True))
            except (TypeError, ValueError):
                return {}
        # Last-resort JSON parse for anything that didn't match the
        # quick-prefix check (covers leading whitespace cases).
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return {}
        return decode_params(parsed) if parsed is not None else {}
    return {}


def all_param_pairs(case: dict) -> list[tuple[str, Any]]:
    """Flatten every param dict on the case (query/body/path/cookie)
    into a single ordered list of (name, value) pairs. The order is
    deterministic so callers can iterate without worrying about which
    column a name came from."""
    pairs: list[tuple[str, Any]] = []
    for col in ("query_params", "body_params", "path_params", "cookie_params"):
        d = decode_params(case.get(col))
        for k, v in d.items():
            pairs.append((str(k), v))
    return pairs
