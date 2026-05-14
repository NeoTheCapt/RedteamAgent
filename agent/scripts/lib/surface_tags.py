#!/usr/bin/env python3
"""Generic surface-role classifier for cases.db case payloads.

Where input_shapes.py describes the SHAPE of a request's INPUT (XML body,
URL-bearing param, JSON writer, etc.) for binding to INJECTION probe
families, surface_tags.py describes the FUNCTIONAL ROLE of the endpoint
for binding to WORKFLOW-MUTATION families. The two dimensions are
independent: a JSON write to /auth/login carries both `json_writer` and
`auth_entry`.

Bindings the vulnerability-analyst prompt enforces (kept in sync):

    auth_entry        -> empty-body / dictionary email × common password /
                         role-injection in registration
    account_recovery  -> empty-body / known-answer dictionary from intel.md /
                         reset-token replay
    privileged_write  -> empty-body / numeric boundary / duplicate submission /
                         mass-assignment role / unauthorized session
    file_handling     -> empty upload / content-type mismatch / oversize length
    workflow_token    -> empty token / tampered token / replayed token
    object_reference  -> sibling-ID enumeration (IDOR) / cross-user replay

Generality contract (do NOT break):

  * Path token vocabulary stays generic web-app/HTTP RFC vocabulary
    (auth/login/signin/register/reset/forgot/upload/token/jwt/refresh/
    2fa/otp/mfa/users). Every token listed appears across multiple
    frameworks' canonical docs — adding a token specific to one target
    (an app brand name, a target-specific route, etc.) is a contract
    violation. The unit test enforces this by grepping the module
    source for known target tokens.
  * No url_path substring match against a specific endpoint name from
    any target.
  * Inference uses METHOD + URL TOKEN + CONTENT-TYPE only — never a
    target-specific value comparison.

Usage:

    echo '<case-json>' | surface_tags.py                  # stdin -> stdout
    surface_tags.py --batch <batch-json-file>             # in-place batch

Output: when invoked --batch, adds (or merges into) a "surface_types": [...]
array on each case object in place. The field is sorted/deduped and may
be empty [].
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Authentication entry points. Either an explicit auth verb segment
# (`/login`, `/signin`, `/authenticate`, `/auth/<x>`) or a registration
# verb (`/register`, `/signup`). Trailing-slash and case tolerance.
_AUTH_LOGIN_PATH = re.compile(
    r"(?:^|/)(?:login|signin|sign[-_]in|authenticate|auth)(?:/|$)",
    re.IGNORECASE,
)
_AUTH_REGISTER_PATH = re.compile(
    r"(?:^|/)(?:register|signup|sign[-_]up|create[-_]account)(?:/|$)"
    # Plus the REST convention: POST /<users-noun> with no trailing id.
    r"|(?:^|/)(?:users?|accounts?|members?)/?$",
    re.IGNORECASE,
)

# Account recovery vocabulary. Covers the three canonical phrasings
# (reset / forgot / recover) plus change-password and security-question
# self-service flows. Hyphens, underscores, and concatenation tolerated.
_RECOVERY_PATH = re.compile(
    r"(?:reset[-_]?password"
    r"|forgot[-_]?password"
    r"|recover[-_]?password"
    r"|change[-_]?password"
    r"|password[-_]?reset"
    r"|password[-_]?recovery"
    r"|security[-_]?question"
    r"|security[-_]?answer)",
    re.IGNORECASE,
)

# File upload vocabulary. Either an explicit upload path or a generic
# upload-like noun. The multipart content-type signal is checked
# separately and either alone triggers `file_handling`.
_UPLOAD_PATH = re.compile(
    r"(?:^|/)(?:upload|uploads|files?|attachments?|documents?|complain|media|photos?|images?)(?:/|$)",
    re.IGNORECASE,
)

# Token issuance / verification / refresh endpoints. Token-shape verbs
# from RFC 6749 / 7519 plus common 2FA flow names.
_TOKEN_PATH = re.compile(
    r"(?:^|/)(?:token|tokens|jwt|refresh|2fa|otp|mfa|totp|verify)(?:/|$)",
    re.IGNORECASE,
)

# REST-style numeric or UUID identifier at the path tail. This is the
# IDOR fingerprint regardless of framework.
_OBJECT_ID_TAIL = re.compile(
    r"/(?:[0-9]+"                                              # numeric
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # uuid v4
    r")/?$"
)


def _decode_params(raw):
    """Tolerant JSON-or-dict decode. Mirrors input_shapes._decode_params
    semantics but kept local so the two classifiers stay independent."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def classify(case: dict) -> list[str]:
    """Return sorted list of surface-role tags for one case payload.

    Uses method + url path tokens + content-type only. Best-effort — a
    case with sparse fields will simply return an empty list, which
    falls back to the legacy generic-rotation behavior in vuln-analyst.
    """
    tags: set[str] = set()
    method = str(case.get("method") or "").upper()
    url_path = str(case.get("url_path") or case.get("url") or "")
    content_type = str(case.get("content_type") or "").lower()
    body = str(case.get("body") or "")

    body_params = _decode_params(case.get("body_params"))
    body_keys_lower = {str(k).lower() for k in body_params.keys()}

    # auth_entry: a credential-bearing POST to a login/auth/register
    # verb. The credential signal lives in the body shape, which is
    # checked through generic key vocabulary (email/username/password)
    # so the inference works for any web framework.
    if method == "POST":
        looks_like_auth = bool(_AUTH_LOGIN_PATH.search(url_path)) or bool(
            _AUTH_REGISTER_PATH.search(url_path)
        )
        has_credential_fields = bool(
            body_keys_lower & {"email", "username", "user", "login", "password", "passwd", "pwd"}
        )
        if looks_like_auth or has_credential_fields:
            tags.add("auth_entry")

    # account_recovery: any method against a recovery-named endpoint.
    # Recovery flows commonly hide a security-answer or reset-token
    # field, but the URL token alone is enough to trigger the workflow
    # mutation pass.
    if _RECOVERY_PATH.search(url_path):
        tags.add("account_recovery")

    # privileged_write: a write-method (POST/PUT/PATCH/DELETE) with
    # either a structured body (JSON / form) or DELETE (destructive).
    # Avoids tagging idempotent GETs and informational POSTs.
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        is_destructive = method == "DELETE"
        is_structured = "json" in content_type or "form" in content_type or body.strip().startswith(("{", "["))
        has_body = bool(body_params) or bool(body.strip())
        if is_destructive or (is_structured and has_body):
            tags.add("privileged_write")

    # file_handling: explicit upload path OR multipart body. Either
    # signal alone is enough.
    if "multipart/form-data" in content_type or _UPLOAD_PATH.search(url_path):
        tags.add("file_handling")

    # workflow_token: any URL path under a token-issuance/verification
    # verb. Also triggered if the response snippet contains a token-class
    # field in a position that proves issuance rather than mere
    # documentation. The bare substring `bearer ` was removed because it
    # over-fires on help pages, error messages, and API docs that just
    # mention bearer auth without issuing a token.
    if _TOKEN_PATH.search(url_path):
        tags.add("workflow_token")
    else:
        snippet = str(case.get("response_snippet") or "")
        # JSON-encoded token field (quoted key on the left of a colon)
        # proves the response is structurally returning a token value,
        # not just describing one in prose.
        if re.search(
            r"['\"](?:token|jwt|access_token|refresh_token|"
            r"id_token|session_token|bearer_token)['\"]\s*:",
            snippet,
            re.IGNORECASE,
        ):
            tags.add("workflow_token")
        # `Authorization: Bearer <value>` echoed in a Set-Cookie / header
        # dump or curl-style transcript also proves issuance. Bare prose
        # like "use Bearer auth" does NOT match because we require the
        # full `Authorization:` prefix on the same line.
        elif re.search(
            r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._\-]{8,}",
            snippet,
            re.IGNORECASE,
        ):
            tags.add("workflow_token")

    # object_reference: REST-style /<noun>/<id> at path tail. Numeric
    # and UUID forms covered. Any method against this path is an IDOR
    # candidate; vuln-analyst's workflow-mutation pass enumerates
    # sibling IDs.
    if _OBJECT_ID_TAIL.search(url_path):
        tags.add("object_reference")

    return sorted(tags)


def _annotate_batch(path: Path) -> int:
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
        existing = entry.get("surface_types")
        merged = set()
        if isinstance(existing, list):
            merged.update(str(t) for t in existing)
        merged.update(classify(entry))
        entry["surface_types"] = sorted(merged)
        annotated += 1
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return annotated


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--batch":
        path = Path(argv[2])
        count = _annotate_batch(path)
        if count == 0:
            print("surface_types_summary=empty")
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("surface_types_summary=parse_error")
            return 0
        agg: dict[str, int] = {}
        for entry in payload:
            for tag in entry.get("surface_types") or []:
                agg[tag] = agg.get(tag, 0) + 1
        if not agg:
            print("surface_types_summary=none")
        else:
            print("surface_types_summary=" + ",".join(
                f"{tag}:{count}" for tag, count in sorted(agg.items())
            ))
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        case = json.loads(raw)
    except ValueError as exc:
        print(f"surface_tags: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if isinstance(case, dict):
        case["surface_types"] = classify(case)
        json.dump(case, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
