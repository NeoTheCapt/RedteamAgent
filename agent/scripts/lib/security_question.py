#!/usr/bin/env python3
"""Generic security-question context detector for case payloads.

When a password-recovery / account-takeover workflow asks the caller to
submit a security-question answer, the case carries enough STRUCTURAL
signal to extract a (identifier, question_text) pair. Once vuln-analyst
records that pair in intel.md's `Security Questions` table, the existing
`intel_changed_check.sh` -> `.osint-respawn-required` machinery dispatches
osint-analyst to research candidate answers and write them back to
auth.json's `security_answer_candidates` array. vuln-analyst then rotates
the candidates against the account-recovery endpoint.

Detection is purely STRUCTURAL — no embedded user name, no hard-coded
question text, no specific answer dictionary. Only:

  * a body / path / response field name from the canonical web-app
    recovery vocabulary (securityQuestion, security_question,
    secretQuestion, secret_question, security_answer, securityAnswer)
  * an identifier shape extractable from the same request (an email
    address pattern, a `username` / `email` / `user` field value)
  * an optional human-readable question text from the response or
    schema (matched conservatively, only accepted when shaped like
    `What ... ?` or `Your ... ?`)

Generality contract:

  * Field-name vocabulary stays generic OWASP recovery-flow names.
  * Identifier extraction matches RFC 5322 email shape only — no
    target-specific username dictionary.
  * Question-text extraction uses a single English interrogative shape
    OR an explicit JSON `question` key. Localized variants can be
    added later as a future generic-vocabulary extension.

Output (JSONL): one line per case. Schema:

    {
      "identifier": "<email or username>",
      "question":   "<question text or empty if structural only>",
      "source":     "<filename hint>",
      "confidence": "HIGH" | "MEDIUM"
    }

`MEDIUM` is used when only the structural marker is found (field-name
present) but no concrete question text — vuln-analyst still records
the (identifier, "unknown question") pair so osint-analyst at least
sees the user is recovery-target.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Canonical recovery-vocabulary field names. Either snake_case or
# camelCase, plus a few aliasing variants. Adding a target-specific
# field name here is a contract violation enforced by the unit test grep.
_RECOVERY_FIELD_NAMES = frozenset({
    "securityquestion", "security_question",
    "secretquestion", "secret_question",
    "securityanswer", "security_answer",
    "secretanswer", "secret_answer",
    "challenge_question", "challengequestion",
    "challenge_answer", "challengeanswer",
    "recoveryquestion", "recovery_question",
    "recoveryanswer", "recovery_answer",
    "answer",   # only counts when paired with question elsewhere
})


# Identifier field names — the user being recovered. Match canonical
# auth vocabulary.
_IDENTIFIER_FIELDS = ("email", "username", "user", "userid", "user_id", "login", "account")


# RFC 5322-ish email shape. Used for both standalone identifier
# extraction and trimming user fields. Generic regex.
_EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")


# Question-shape detection. We accept either:
#   * a quoted JSON `"question"` key followed by a string, OR
#   * an English interrogative ("What is …?", "Where were you …?",
#     "Who was your …?", "Your favorite …?", "Name of your …?").
# Conservative — false positives waste OSINT time, so we'd rather miss
# than over-trigger.
_QUESTION_KEY_RE = re.compile(
    r'["\'](?:question|securityQuestion|secret_question|securityquestion|'
    r'security_question|recovery_question|recoveryquestion)["\']\s*:\s*'
    r'["\']([^"\']{6,200})["\']',
    re.IGNORECASE,
)


_QUESTION_TEXT_RE = re.compile(
    r"(?:^|[\s>])"
    r"(?P<text>(?:What|Where|When|Who|Why|How|Your|Name of your|Your favorite)\s+"
    r"[A-Za-z][\w'\s,.\-]{4,160}\?)",
    re.IGNORECASE,
)


def _decode_params(raw) -> dict:
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


def _normalize(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name).lower()


def _has_recovery_field(params: dict) -> bool:
    if not params:
        return False
    for key in params.keys():
        norm = _normalize(str(key))
        if norm in {_normalize(n) for n in _RECOVERY_FIELD_NAMES}:
            return True
    return False


def _extract_identifier(params: dict, body: str, headers: str) -> str:
    # Direct field hit.
    for field in _IDENTIFIER_FIELDS:
        value = params.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        # case-insensitive
        for k, v in params.items():
            if isinstance(k, str) and k.lower() == field and isinstance(v, str) and v.strip():
                return v.strip()
    # Email pattern in body / headers.
    for blob in (body, headers):
        if blob:
            m = _EMAIL_PATTERN.search(blob)
            if m:
                return m.group(0)
    return ""


def _extract_question_text(response_snippet: str, body: str) -> str:
    """Best-effort. Prefer the JSON `question` key form; fall back to
    a free-form interrogative pattern in the response."""
    for source in (response_snippet, body):
        if not source:
            continue
        m = _QUESTION_KEY_RE.search(source)
        if m:
            return m.group(1).strip()
    for source in (response_snippet, body):
        if not source:
            continue
        m = _QUESTION_TEXT_RE.search(source)
        if m:
            text = m.group("text").strip()
            # Reject overly long matches that swallow nearby HTML.
            if len(text) <= 200:
                return text
    return ""


def detect(case: dict) -> dict | None:
    if not isinstance(case, dict):
        return None

    method = str(case.get("method") or "").upper()
    # Only POST / PUT / PATCH writes can submit an answer; GETs can
    # return the question text but never trigger the recovery action.
    # Detection runs on both since vuln-analyst may have seen the
    # question-presenting GET first.
    url_path = str(case.get("url_path") or case.get("url") or "")
    if not url_path:
        return None

    body = str(case.get("body") or "")
    headers = str(case.get("headers") or "")
    snippet = str(case.get("response_snippet") or "")

    params = {}
    for col in ("body_params", "query_params", "path_params", "cookie_params"):
        params.update(_decode_params(case.get(col)))

    has_field = _has_recovery_field(params)
    question_text = _extract_question_text(snippet, body)

    # We need at least one of: (a) explicit recovery field name, OR
    # (b) a recovery URL token paired with an extractable question.
    url_lower = url_path.lower()
    looks_like_recovery_path = bool(re.search(
        r"reset[-_]?password|forgot[-_]?password|recover[-_]?password|"
        r"change[-_]?password|security[-_]?question|security[-_]?answer",
        url_lower,
    ))

    if not has_field and not (looks_like_recovery_path and question_text):
        return None

    identifier = _extract_identifier(params, body, headers)
    if not identifier:
        # Without an identifier, OSINT has nothing to search for.
        return None

    confidence = "HIGH" if (has_field and question_text) else "MEDIUM"

    return {
        "identifier": identifier,
        "question": question_text,
        "source": str(case.get("source") or case.get("url_path") or ""),
        "confidence": confidence,
    }


def _annotate_batch(path: Path) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (0, 0)
    if not isinstance(payload, list):
        return (0, 0)
    total = 0
    detected = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        total += 1
        result = detect(entry)
        if result:
            entry["security_context"] = result
            detected += 1
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return (total, detected)


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--batch":
        path = Path(argv[2])
        total, detected = _annotate_batch(path)
        if total == 0:
            print("security_context_summary=empty")
        else:
            print(f"security_context_summary=detected:{detected},total:{total}")
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        case = json.loads(raw)
    except ValueError as exc:
        print(f"security_question: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if isinstance(case, dict):
        result = detect(case)
        if result:
            case["security_context"] = result
        json.dump(case, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
