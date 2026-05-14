#!/usr/bin/env python3
"""Generic cryptographic-forgery primitive extractor.

Source-analyzer currently emits each discovered secret as a single
disclosure finding (HIGH/MEDIUM/LOW). But a SECRET alone is not a forge
primitive. To craft a forged signed value, an attacker also needs:

  (a) the ALGORITHM used to sign (HS256, HMAC-SHA256, RS256, ...)
  (b) a SAMPLE of an already-signed value (a JWT, a signed cookie, an
      HMAC-tagged token) that the server is willing to accept

When all three appear in the same source body, the operator can hand
off ONE finding to exploit-developer with everything needed to attempt
a forge in one bounded step. Without this co-location, the same
information stays scattered across multiple findings and the forge
attempt never happens.

Detection is purely STRUCTURAL — RFC-vocabulary regex matches for
algorithm names, RFC 7519 JWT shape, PEM block headers, common
language-specific HMAC API call patterns. No target-specific tokens.

Generality contract (do NOT break):

  * Algorithm vocabulary stays canonical RFC names (HS256/HS384/HS512/
    RS256/RS384/RS512/ES256/ES384/ES512/PS256/PS384/PS512/EdDSA/none).
    Adding a target-specific algorithm is a contract violation.
  * Secret/sample patterns match by SHAPE (length, charset, surrounding
    delimiter, language-specific API call). Never by a literal value.
  * False-positive control: a `secret` candidate alone does not emit a
    primitive. A `sample` alone does not emit a primitive. The
    primitive is only emitted when at least TWO of the three components
    (algorithm + secret + sample) co-locate in the same body.

Output: one JSONL row per primitive. Schema:

    {
      "kind":      "jwt_signing" | "hmac_signed" | "rsa_signed",
      "algorithm": "<canonical>",
      "secret":    "<value>",        # full value; the operator's
                                     # findings.md is treated as sensitive
                                     # already, and the exploit-developer
                                     # needs the full secret to forge
      "sample":    "<sample value>",
      "source":    "<filename / url>",
      "evidence":  "<one-line context excerpt>",
      "confidence": "HIGH" | "MEDIUM"
    }

Usage:

    cat bundle.js | forgery_primitives.py --source bundle.js
    forgery_primitives.py /path/to/main.js
    forgery_primitives.py --mask /path/to/main.js   # emit redacted values
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Canonical signing-algorithm vocabulary — from JOSE / RFC 7518 / RFC 8032.
_ALGORITHM_NAMES = frozenset({
    "HS256", "HS384", "HS512",
    "RS256", "RS384", "RS512",
    "ES256", "ES256K", "ES384", "ES512",
    "PS256", "PS384", "PS512",
    "EdDSA", "Ed25519", "Ed448",
    "none",
})


# RFC 7519 JWT shape. Three base64url segments separated by dots. The
# header always starts with `eyJ` (`{"` base64url-encoded) so we anchor on
# that to avoid matching arbitrary three-segment base64 strings.
_JWT_SAMPLE = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)


# Algorithm name appearing in code or config. Always quoted or used as
# an identifier — never appears as plain English.
_ALGORITHM_TOKEN = re.compile(
    r"['\"]?(?P<alg>"
    r"HS(?:256|384|512)|RS(?:256|384|512)|ES(?:256(?:K)?|384|512)|"
    r"PS(?:256|384|512)|EdDSA|Ed(?:25519|448)|none"
    r")['\"]?",
)


# Secret literal pattern. Matches a quoted string of >=8 printable
# characters following a key-shaped identifier (`secret`, `key`,
# `signing_key`, `jwt_secret`, `password`, ...).
_SECRET_DECL = re.compile(
    r"(?xi)"
    r"(?P<name>[\w.\-]*(?:secret|signing[_-]?key|signkey|hmac[_-]?key|"
    r"jwt[_-]?key|jwt[_-]?secret|api[_-]?secret|access[_-]?secret|"
    r"sign[_-]?secret|app[_-]?secret|client[_-]?secret|symmetric[_-]?key|"
    r"shared[_-]?secret|private[_-]?key|encryption[_-]?key|salt))"
    r"\s*[:=]\s*['\"]"
    r"(?P<value>[^'\"]{6,128})"
    r"['\"]"
)


# HMAC API call site detection across the common ecosystems.
_HMAC_CALL = re.compile(
    r"(?xi)"
    r"(?:"
    r"crypto\.createHmac\s*\(\s*['\"](?P<alg_node>[a-zA-Z0-9_\-]+)['\"]"
    r"|hmac\.new\s*\(\s*[^,]+\s*,\s*[^,]*,\s*(?:hashlib\.)?(?P<alg_py>[A-Za-z0-9_]+)"
    r"|hash_hmac\s*\(\s*['\"](?P<alg_php>[a-zA-Z0-9_\-]+)['\"]"
    r"|OpenSSL::HMAC\.hexdigest\s*\(\s*['\"](?P<alg_rb>[a-zA-Z0-9_\-]+)['\"]"
    r"|hmac\.New\s*\(\s*(?P<alg_go>[a-zA-Z0-9_.]+)"
    r")"
)


# JWT signing API call site detection. Captures both the secret arg
# position and the algorithm option when present.
_JWT_SIGN_CALL = re.compile(
    r"(?xi)"
    r"(?:"
    r"jwt\.sign\s*\("                            # node jsonwebtoken
    r"|jwt\.encode\s*\("                         # python PyJWT
    r"|JWT\.encode\s*\("                         # ruby jwt
    r"|Jwts\.builder\b"                          # java jjwt
    r"|sign\s*\(\s*[^,]+,\s*[^,]+,\s*\{[^}]*algorithm"  # generic options arg
    r")"
)


# PEM private key block (RSA/EC/Ed25519). Anchor on the standard armor.
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |ED25519 )?PRIVATE KEY-----"
    r".*?"
    r"-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |ED25519 )?PRIVATE KEY-----",
    re.DOTALL,
)


# Hex / base64 sample value that looks like an HMAC or signed token tag.
# 32/40/48/64/96/128 hex chars covers SHA-1/256/384/512 + truncations.
# Base64 segment >= 20 chars catches encoded MAC tags.
_TAG_SAMPLE = re.compile(
    r"(?:"
    r"\b[a-fA-F0-9]{32,128}\b"                  # hex tag
    r"|"
    r"\b[A-Za-z0-9+/]{20,}={0,2}\b"             # base64 tag
    r")"
)


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return value
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def _excerpt(text: str, start: int, end: int, width: int = 60) -> str:
    """Return a single-line excerpt of `width` characters around the
    match, with whitespace collapsed."""
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    snippet = text[lo:hi]
    return re.sub(r"\s+", " ", snippet).strip()


def _collect_algorithms(text: str) -> list[tuple[str, int, int]]:
    """All canonical algorithm tokens in text, with positions."""
    out = []
    for m in _ALGORITHM_TOKEN.finditer(text):
        alg = m.group("alg")
        # Drop ALG_NONE-looking standalone words that don't mean the
        # JOSE `none` algorithm (e.g. variable named "none"). We accept
        # only the explicit form `"none"`/`'none'`.
        if alg == "none":
            if not (m.group(0).startswith(("'", '"')) and m.group(0).endswith(("'", '"'))):
                continue
        out.append((alg, m.start(), m.end()))
    return out


def _collect_secrets(text: str) -> list[tuple[str, str, int, int]]:
    """All secret-declaration hits, returning (name, value, start, end)."""
    out = []
    for m in _SECRET_DECL.finditer(text):
        out.append((m.group("name"), m.group("value"), m.start(), m.end()))
    return out


def _collect_jwt_samples(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _JWT_SAMPLE.finditer(text)]


def _collect_pem_keys(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _PEM_PRIVATE_KEY.finditer(text)]


def _collect_hmac_calls(text: str) -> list[tuple[str, int, int]]:
    """HMAC API call sites, capturing the algorithm argument when present."""
    out = []
    for m in _HMAC_CALL.finditer(text):
        for key in ("alg_node", "alg_py", "alg_php", "alg_rb", "alg_go"):
            alg = m.group(key)
            if alg:
                out.append((alg, m.start(), m.end()))
                break
    return out


def _within(span_a: tuple[int, int], span_b: tuple[int, int], window: int = 800) -> bool:
    """Two spans are 'co-located' if their nearest edges are within
    `window` characters. Generous default — same file/bundle slice."""
    a0, a1 = span_a
    b0, b1 = span_b
    if a1 < b0:
        return (b0 - a1) <= window
    if b1 < a0:
        return (a0 - b1) <= window
    return True


def extract(text: str, source: str = "stdin") -> list[dict]:
    """Detect (algorithm + secret + sample) triples in `text` and emit
    one structured primitive per triple. Returns a list of dict rows."""
    if not text:
        return []
    primitives: list[dict] = []

    algorithms = _collect_algorithms(text)
    secrets = _collect_secrets(text)
    jwts = _collect_jwt_samples(text)
    pems = _collect_pem_keys(text)
    hmac_calls = _collect_hmac_calls(text)

    seen: set[tuple[str, str, str, str]] = set()  # dedup signatures

    # ----- jwt_signing -----
    # A JWT sample plus EITHER an algorithm token OR an HMAC/JWT signing
    # call within the same window. Pair with the closest secret literal.
    for sample, s_start, s_end in jwts:
        sample_span = (s_start, s_end)
        # Pair with an algorithm token nearby.
        chosen_alg = ""
        chosen_alg_span = (-1, -1)
        for alg, a_start, a_end in algorithms:
            alg_span = (a_start, a_end)
            if _within(sample_span, alg_span):
                chosen_alg = alg
                chosen_alg_span = alg_span
                break
        if not chosen_alg:
            # No explicit algorithm in source — still emit at lower
            # confidence if a secret literal is near the sample, since
            # the JWT header itself encodes the algorithm at runtime.
            chosen_alg = "unknown"
        # Find the nearest secret literal within the window.
        chosen_secret = ""
        for name, value, ss, se in secrets:
            if _within(sample_span, (ss, se)):
                chosen_secret = value
                break
        if not chosen_secret and chosen_alg == "unknown":
            continue
        sig = ("jwt_signing", chosen_alg, chosen_secret, sample)
        if sig in seen:
            continue
        seen.add(sig)
        primitives.append({
            "kind": "jwt_signing",
            "algorithm": chosen_alg,
            "secret": chosen_secret,
            "sample": sample,
            "source": source,
            "evidence": _excerpt(text, s_start, s_end),
            "confidence": "HIGH" if chosen_secret and chosen_alg != "unknown" else "MEDIUM",
        })

    # ----- hmac_signed -----
    # An HMAC call site provides the algorithm; pair with the nearest
    # secret literal and the nearest hex/base64 tag sample.
    for alg, h_start, h_end in hmac_calls:
        call_span = (h_start, h_end)
        chosen_secret = ""
        for name, value, ss, se in secrets:
            if _within(call_span, (ss, se)):
                chosen_secret = value
                break
        chosen_sample = ""
        for tag_m in _TAG_SAMPLE.finditer(text):
            t_span = (tag_m.start(), tag_m.end())
            # Avoid re-using a known JWT segment as the HMAC sample.
            if any(t_span[0] >= j[1] and t_span[1] <= j[2] for j in jwts):
                continue
            if _within(call_span, t_span):
                chosen_sample = tag_m.group(0)
                break
        if not chosen_secret and not chosen_sample:
            continue
        sig = ("hmac_signed", alg, chosen_secret, chosen_sample)
        if sig in seen:
            continue
        seen.add(sig)
        primitives.append({
            "kind": "hmac_signed",
            "algorithm": alg,
            "secret": chosen_secret,
            "sample": chosen_sample,
            "source": source,
            "evidence": _excerpt(text, h_start, h_end),
            "confidence": "HIGH" if chosen_secret and chosen_sample else "MEDIUM",
        })

    # ----- rsa_signed -----
    # A PEM private key in source is itself a forgery primitive — the
    # algorithm is implicit (the PEM header carries it). Pair with the
    # nearest JWT or hex/base64 tag sample.
    for pem, p_start, p_end in pems:
        pem_span = (p_start, p_end)
        algorithm = "RS256"  # canonical RSA-SHA256 default
        if "EC PRIVATE KEY" in pem or "EC " in pem[:30]:
            algorithm = "ES256"
        elif "ED25519" in pem.upper():
            algorithm = "EdDSA"
        chosen_sample = ""
        for jw, js, je in jwts:
            if _within(pem_span, (js, je)):
                chosen_sample = jw
                break
        sig = ("rsa_signed", algorithm, pem[:60], chosen_sample)
        if sig in seen:
            continue
        seen.add(sig)
        primitives.append({
            "kind": "rsa_signed",
            "algorithm": algorithm,
            "secret": pem,
            "sample": chosen_sample,
            "source": source,
            "evidence": "PEM private key block in source",
            "confidence": "HIGH",
        })

    return primitives


def _format(rows: list[dict], mask: bool) -> list[dict]:
    if not mask:
        return rows
    out = []
    for row in rows:
        new = dict(row)
        new["secret"] = _mask(str(row.get("secret") or ""))
        new["sample"] = _mask(str(row.get("sample") or ""))
        out.append(new)
    return out


def main(argv: list[str]) -> int:
    args = argv[1:]
    source = "stdin"
    mask = False
    path: Path | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--source" and i + 1 < len(args):
            source = args[i + 1]
            i += 2
            continue
        if a == "--mask":
            mask = True
            i += 1
            continue
        if a.startswith("-"):
            print(f"forgery_primitives: unknown option {a}", file=sys.stderr)
            return 2
        path = Path(a)
        i += 1

    if path is not None:
        if not path.is_file():
            print(f"forgery_primitives: not a file: {path}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if source == "stdin":
            source = str(path)
    else:
        text = sys.stdin.read()

    primitives = extract(text, source=source)
    for row in _format(primitives, mask):
        sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
