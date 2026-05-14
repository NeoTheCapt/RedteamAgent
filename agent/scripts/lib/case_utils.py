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
from typing import Any


def decode_params(raw: Any) -> dict:
    """Return a dict view of a case's query / body / path / cookie
    params. Tolerates every shape the producers emit:

      * dict — return as-is
      * list of [k, v] pairs — flatten to dict
      * JSON-encoded string — parse and recurse
      * None / empty — return {}

    Never raises. Unknown shapes become {} so caller's downstream
    membership checks short-circuit on empty input.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        out: dict = {}
        for entry in raw:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                out[str(entry[0])] = entry[1]
        return out
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return decode_params(parsed)
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
