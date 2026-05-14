#!/usr/bin/env python3
"""Generic stateful-response detector for case payloads.

Track A binds 6 surface tags to required workflow mutations (empty-body,
duplicate ×3, boundary, mass-assignment, unauthorized session). That
covers most "submit and forget" write bugs. The residual gap is multi-
step state bugs:

  * accumulation:    duplicate submission increments a counter (Multiple
                     Likes, Mass Dispel)
  * state pivot:     a successful write returns an id/balance/quantity
                     that an attacker can target in a follow-up (Wallet
                     Depletion, Mint the Honey Pot)
  * cross-session:   a state mutation is accepted by one session but
                     should reflect for / be inaccessible to another
                     (Manipulate Basket, View Basket)

These bugs require **read-back verification** — fire the write, observe
the response (or a follow-up GET), and compare to baseline. Vuln-analyst
won't do that for every case (probe budget), so we gate the extra step
on a structural signal: does the response shape say "I mutated state"?

Generic stateful markers (web-app vocabulary, never target-specific):

  * Response body contains a key from {id, _id, uuid, count, total,
    balance, quantity, amount, score, status, version, etag, revision,
    created_at, updated_at, deleted_at, expires_at}.
  * Response status is 201 (Created) or 204 (No Content with Location).
  * Response status is 200 AND the body is JSON containing a numeric
    value alongside one of the stateful keys.

Generality contract:

  * Marker vocabulary stays generic web/HTTP/REST vocabulary. Every
    name appears in JSON:API / OpenAPI / HAL canonical specs.
  * Detection runs on response shape only; no target-specific key.
  * Negative-baseline: a plain `{"ok": true}` or HTML error page does
    NOT trigger.

Output: when invoked --batch, annotates each case with a boolean
`stateful_response` field. When invoked stdin->stdout, emits the same
object with the field added.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Generic stateful field names. Each appears in JSON:API / HAL / OpenAPI
# canonical examples. Adding a target-specific key here would be a
# contract violation enforced by the unit test grep.
#
# Post-M1 fix: dropped `status`, `state`, `phase`, `version` from the
# set. Those four over-fire on extremely common non-mutating responses:
#   * `{"status":"ok"}` — every ack response in every framework
#   * `{"appName":"x","version":"1.2.3"}` — every config / metadata GET
#   * `{"phase":"prod","state":"active"}` — env / health endpoints
# The 201/202/204 status-code branch still catches genuine state
# mutations that signal only via response code. `etag`/`revision`/`rev`
# stay in the set because they're unambiguous resource-versioning
# markers (rarely appear on metadata responses).
_STATEFUL_KEYS = frozenset({
    # identifiers
    "id", "_id", "uuid", "guid",
    # counts / quantities
    "count", "total", "quantity", "qty", "amount", "balance", "score",
    "likes", "votes", "rating",
    # resource versioning / locks (NOT app version)
    "etag", "revision", "rev",
    # timestamps
    "created_at", "updated_at", "deleted_at", "expires_at",
    "createdAt", "updatedAt", "deletedAt", "expiresAt",
    # cardinality of side effects
    "affected", "modified", "matched",
})


# Status codes that strongly imply state mutation happened.
_STATEFUL_STATUS_CODES = frozenset({201, 202, 204})


def _decode_json_object(snippet: str) -> dict | None:
    """Best-effort: extract the first JSON object from a response snippet.
    Tolerates leading whitespace, trailing chatter, JSONP-style wrappers."""
    if not snippet:
        return None
    text = snippet.strip()
    if not text:
        return None
    # Strip JSONP wrapper: `callback(<json>)`
    m = re.match(r"^[a-zA-Z_][\w$.]*\((.*)\)\s*;?\s*$", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    # Fall back to extracting the first balanced {...} block.
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start : i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _has_stateful_key(obj: dict, depth: int = 0) -> bool:
    """Recursive scan for stateful key names. Capped depth to bound
    cost on huge responses. Case-insensitive.

    Post-L3 fix: depth cap raised from 4 to 6 to handle JSON:API
    framework responses which commonly nest like
    `{data: {attributes: {meta: {audit: {created_at: ...}}}}}` — a
    depth-5 structure that pre-L3 silently fell through to False."""
    if depth > 6 or not isinstance(obj, dict):
        return False
    for key, value in obj.items():
        if not isinstance(key, str):
            continue
        if key in _STATEFUL_KEYS or key.lower() in _STATEFUL_KEYS:
            return True
        if isinstance(value, dict):
            if _has_stateful_key(value, depth + 1):
                return True
        elif isinstance(value, list):
            for entry in value[:8]:  # don't walk huge arrays
                if isinstance(entry, dict) and _has_stateful_key(entry, depth + 1):
                    return True
    return False


def is_stateful(case: dict) -> bool:
    """Return True when this case's response shape implies a state
    mutation occurred. Used by vuln-analyst to decide whether to spend
    extra budget on read-back / accumulation / cross-session probes.

    Narrowed to WRITE methods only — GET responses that return ids /
    balances are about object_reference IDOR (handled by surface_tags)
    not stateful-write follow-up. A write-method false-negative is
    cheap (the agent falls back to A's existing privileged_write
    mutations); a GET false-positive would burn probe budget on
    read-only data."""
    if not isinstance(case, dict):
        return False

    method = str(case.get("method") or "").upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False

    status = case.get("response_status")
    snippet = str(case.get("response_snippet") or "")

    # Strong signal: 201/202/204 from a write method.
    try:
        status_int = int(status) if status is not None else 0
    except (TypeError, ValueError):
        status_int = 0
    if status_int in _STATEFUL_STATUS_CODES:
        return True

    # JSON body with a stateful key.
    obj = _decode_json_object(snippet)
    if obj is not None and _has_stateful_key(obj):
        return True

    # Plain-text fallback: snippet contains a stateful key in
    # quoted-JSON position, even if we couldn't parse it cleanly.
    for key in _STATEFUL_KEYS:
        # Match `"key":` form, common JSON serialization.
        if re.search(r"[\"']" + re.escape(key) + r"[\"']\s*:", snippet):
            return True

    return False


def _annotate_batch(path: Path) -> tuple[int, int]:
    """Annotate each case with `stateful_response`. Returns (total, stateful)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (0, 0)
    if not isinstance(payload, list):
        return (0, 0)
    total = 0
    stateful = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        total += 1
        flag = is_stateful(entry)
        entry["stateful_response"] = flag
        if flag:
            stateful += 1
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return (total, stateful)


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--batch":
        path = Path(argv[2])
        total, stateful = _annotate_batch(path)
        if total == 0:
            print("stateful_summary=empty")
        else:
            print(f"stateful_summary=stateful:{stateful},total:{total}")
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        case = json.loads(raw)
    except ValueError as exc:
        print(f"stateful_response: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if isinstance(case, dict):
        case["stateful_response"] = is_stateful(case)
        json.dump(case, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
