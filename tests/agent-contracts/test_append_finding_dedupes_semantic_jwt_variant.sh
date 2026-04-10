#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/append-finding-dedupe.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"

cat >"$ENG_DIR/findings.md" <<'EOF'
# Findings

- **Finding Count**: 1

## [FINDING-VA-003] Unsigned JWT accepted on protected authentication-details endpoint
- **Discovered by**: vulnerability-analyst
- **Severity**: HIGH
- **OWASP Category**: A07:2021 Identification and Authentication Failures
- **Type**: JWT Signature Verification Bypass (`alg:none`)
- **Parameter**: `Authorization: Bearer <JWT>` in `GET /rest/user/authentication-details/`
- **Evidence**: `scans/case137_none.body` returned `200 OK` with an unsigned `alg:none` JWT and exposed 22 user records.
- **Impact**: An attacker can bypass JWT signature validation with an unsigned token.
EOF

cat >"$TMP_DIR/candidate.md" <<'EOF'
## [FINDING-ID] Protected endpoint accepts unsigned JWT tokens
- **Discovered by**: vulnerability-analyst
- **Severity**: HIGH
- **OWASP Category**: A07:2021 Identification and Authentication Failures
- **Type**: JWT Signature Validation Bypass (`alg:none`)
- **Parameter**: `GET /rest/user/authentication-details/`
- **Evidence**: `scans/case137_none.body` returned `200` with an unsigned `alg:none` JWT and exposed 22 user records.
- **Impact**: An attacker can forge authentication tokens without a valid signature.
EOF

stdout="$("$REPO_ROOT/agent/scripts/append_finding.sh" "$ENG_DIR" "vulnerability-analyst" "$TMP_DIR/candidate.md" 2>"$TMP_DIR/stderr.txt")"
stderr="$(cat "$TMP_DIR/stderr.txt")"

[[ "$stdout" == "FINDING-VA-003" ]] || {
  echo "expected existing finding id, got: $stdout" >&2
  exit 1
}
[[ "$stderr" == *"duplicate finding already present as FINDING-VA-003"* ]] || {
  echo "expected duplicate diagnostic, got: $stderr" >&2
  exit 1
}

count="$(rg -c '^## \[FINDING-' "$ENG_DIR/findings.md")"
[[ "$count" == "1" ]] || {
  echo "expected exactly one finding after dedupe, got: $count" >&2
  cat "$ENG_DIR/findings.md" >&2
  exit 1
}

grep -F -- '- **Finding Count**: 1' "$ENG_DIR/findings.md" >/dev/null || {
  echo "finding count header was not preserved" >&2
  cat "$ENG_DIR/findings.md" >&2
  exit 1
}

echo "append_finding semantic JWT variant dedupe: ok"
