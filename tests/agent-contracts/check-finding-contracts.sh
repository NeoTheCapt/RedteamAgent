#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ALLOCATE_SCRIPT="$ROOT_DIR/agent/scripts/allocate_finding_id.sh"
APPEND_SCRIPT="$ROOT_DIR/agent/scripts/append_finding.sh"
CHECK_SCRIPT="$ROOT_DIR/agent/scripts/check_findings_integrity.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_script() {
  local path="$1"
  [[ -x "$path" ]] || fail "missing executable script: $path"
}

make_engagement_dir() {
  local dir
  dir=$(mktemp -d "${TMPDIR:-/tmp}/finding-contracts.XXXXXX")
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 0
EOF
  printf '%s\n' "$dir"
}

test_allocate_next_id_uses_prefix_max() {
  local dir
  dir=$(make_engagement_dir)
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 4

## [FINDING-VA-001] First
## [FINDING-SA-002] Other
## [FINDING-VA-003] Third
## [FINDING-EX-004] Exploit
EOF

  local va_id sa_id
  va_id=$("$ALLOCATE_SCRIPT" "$dir" vulnerability-analyst)
  sa_id=$("$ALLOCATE_SCRIPT" "$dir" source-analyzer)
  [[ "$va_id" == "FINDING-VA-004" ]] || fail "expected FINDING-VA-004, got $va_id"
  [[ "$sa_id" == "FINDING-SA-003" ]] || fail "expected FINDING-SA-003, got $sa_id"
  rm -rf "$dir"
}

test_integrity_check_accepts_empty_findings() {
  local dir out
  dir=$(make_engagement_dir)
  out=$(mktemp "${TMPDIR:-/tmp}/finding-check.XXXXXX")
  "$CHECK_SCRIPT" "$dir" >"$out" 2>&1 || fail "integrity check should pass on empty findings.md"
  rg 'findings integrity: ok' "$out" >/dev/null || fail "missing clean integrity output"

  rm -f "$out"
  rm -rf "$dir"
}

test_allocate_next_id_ignores_binary_noise() {
  local dir va_id
  dir=$(make_engagement_dir)
  python3 - <<'PY' "$dir/findings.md"
from pathlib import Path
path = Path(__import__('sys').argv[1])
path.write_bytes(b"# Findings\n\n- **Finding Count**: 2\n\n## [FINDING-VA-001] First\n\x00\n## [FINDING-VA-003] Third\n")
PY

  va_id=$("$ALLOCATE_SCRIPT" "$dir" vulnerability-analyst)
  [[ "$va_id" == "FINDING-VA-004" ]] || fail "expected FINDING-VA-004 with binary noise present, got $va_id"
  rm -rf "$dir"
}

test_append_assigns_unique_ids_under_lock() {
  local dir body_a body_b
  dir=$(make_engagement_dir)
  body_a=$(mktemp "${TMPDIR:-/tmp}/finding-body-a.XXXXXX")
  body_b=$(mktemp "${TMPDIR:-/tmp}/finding-body-b.XXXXXX")

  cat >"$body_a" <<'EOF'
## [FINDING-ID] First appended finding
- **Discovered by**: vulnerability-analyst
- **Severity**: MEDIUM
EOF

  cat >"$body_b" <<'EOF'
## [FINDING-ID] Second appended finding
- **Discovered by**: vulnerability-analyst
- **Severity**: LOW
EOF

  "$APPEND_SCRIPT" "$dir" vulnerability-analyst "$body_a" &
  local pid_a=$!
  "$APPEND_SCRIPT" "$dir" vulnerability-analyst "$body_b" &
  local pid_b=$!
  wait "$pid_a"
  wait "$pid_b"

  local count
  count=$(rg -c '^## \[FINDING-VA-' "$dir/findings.md")
  [[ "$count" == "2" ]] || fail "expected 2 appended findings, got $count"
  rg '^## \[FINDING-VA-001\]' "$dir/findings.md" >/dev/null || fail "missing FINDING-VA-001"
  rg '^## \[FINDING-VA-002\]' "$dir/findings.md" >/dev/null || fail "missing FINDING-VA-002"
  rg 'Finding Count.*2' "$dir/findings.md" >/dev/null || fail "finding count not updated to 2"

  rm -f "$body_a" "$body_b"
  rm -rf "$dir"
}

test_append_reuses_existing_id_for_duplicate_title() {
  local dir existing_body duplicate_body appended_id duplicate_id count
  dir=$(make_engagement_dir)
  existing_body=$(mktemp "${TMPDIR:-/tmp}/finding-existing.XXXXXX")
  duplicate_body=$(mktemp "${TMPDIR:-/tmp}/finding-duplicate.XXXXXX")

  cat >"$existing_body" <<'EOF'
## [FINDING-ID] JWTs expose sensitive user claims and do not expire
- **Discovered by**: vulnerability-analyst
- **Severity**: MEDIUM
EOF

  cat >"$duplicate_body" <<'EOF'
## [FINDING-ID] JWTs expose sensitive user claims and do not expire
- **Discovered by**: vulnerability-analyst
- **Severity**: MEDIUM
- **Type**: Sensitive Token Claims / Missing Expiration
EOF

  appended_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$existing_body")
  duplicate_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$duplicate_body")

  [[ "$appended_id" == "FINDING-VA-001" ]] || fail "expected FINDING-VA-001, got $appended_id"
  [[ "$duplicate_id" == "FINDING-VA-001" ]] || fail "expected duplicate append to reuse FINDING-VA-001, got $duplicate_id"

  count=$(rg -c '^## \[FINDING-VA-' "$dir/findings.md")
  [[ "$count" == "1" ]] || fail "expected duplicate title to be skipped, got $count findings"
  rg 'Finding Count.*1' "$dir/findings.md" >/dev/null || fail "finding count not updated to 1"

  rm -f "$existing_body" "$duplicate_body"
  rm -rf "$dir"
}

test_append_reuses_existing_id_for_duplicate_signature() {
  local dir existing_body duplicate_body appended_id duplicate_id count
  dir=$(make_engagement_dir)
  existing_body=$(mktemp "${TMPDIR:-/tmp}/finding-existing.XXXXXX")
  duplicate_body=$(mktemp "${TMPDIR:-/tmp}/finding-duplicate.XXXXXX")

  cat >"$existing_body" <<'EOF'
## [FINDING-ID] Unauthenticated /rest/memories/ leaks user credentials and roles
- **Discovered by**: vulnerability-analyst
- **Severity**: HIGH
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Unauthenticated Sensitive Data Exposure / Excessive Data Exposure
- **Parameter**: none in `GET /rest/memories/`
EOF

  cat >"$duplicate_body" <<'EOF'
## [FINDING-ID] Unauthenticated sensitive data exposure in memories API
- **Discovered by**: vulnerability-analyst
- **Severity**: HIGH
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Unauthenticated Sensitive Data Exposure
- **Parameter**: `/rest/memories/`
- **Evidence**: Both unauthenticated and authenticated GET requests returned HTTP 200 with identical responses.
EOF

  appended_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$existing_body")
  duplicate_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$duplicate_body")

  [[ "$appended_id" == "FINDING-VA-001" ]] || fail "expected FINDING-VA-001, got $appended_id"
  [[ "$duplicate_id" == "FINDING-VA-001" ]] || fail "expected duplicate signature append to reuse FINDING-VA-001, got $duplicate_id"

  count=$(rg -c '^## \[FINDING-VA-' "$dir/findings.md")
  [[ "$count" == "1" ]] || fail "expected duplicate signature to be skipped, got $count findings"
  rg 'Finding Count.*1' "$dir/findings.md" >/dev/null || fail "finding count not updated to 1"

  rm -f "$existing_body" "$duplicate_body"
  rm -rf "$dir"
}

test_integrity_check_detects_duplicates_and_count_mismatch() {
  local dir out
  dir=$(make_engagement_dir)
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 3

## [FINDING-VA-001] Reused title
- **Severity**: HIGH

## [FINDING-VA-001] Reused title
- **Severity**: HIGH
EOF

  out=$(mktemp "${TMPDIR:-/tmp}/finding-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    fail "integrity check should fail on duplicate IDs and mismatched count"
  fi
  rg 'Duplicate finding IDs' "$out" >/dev/null || fail "missing duplicate ID failure output"
  rg 'Duplicate finding titles' "$out" >/dev/null || fail "missing duplicate title failure output"
  rg 'Finding count mismatch' "$out" >/dev/null || fail "missing finding count mismatch output"

  rm -f "$out"
  rm -rf "$dir"
}

test_integrity_check_detects_duplicate_signatures() {
  local dir out
  dir=$(make_engagement_dir)
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 2

## [FINDING-VA-001] Unauthenticated /rest/memories/ leaks user credentials and roles
- **Severity**: HIGH
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Unauthenticated Sensitive Data Exposure / Excessive Data Exposure
- **Parameter**: none in `GET /rest/memories/`

## [FINDING-VA-002] Unauthenticated sensitive data exposure in memories API
- **Severity**: HIGH
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Unauthenticated Sensitive Data Exposure
- **Parameter**: `/rest/memories/`
EOF

  out=$(mktemp "${TMPDIR:-/tmp}/finding-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    fail "integrity check should fail on duplicate signatures"
  fi
  rg 'Duplicate finding signatures' "$out" >/dev/null || fail "missing duplicate signature failure output"

  rm -f "$out"
  rm -rf "$dir"
}

test_append_reuses_existing_id_for_duplicate_artifact_evidence() {
  local dir existing_body duplicate_body appended_id duplicate_id count
  dir=$(make_engagement_dir)
  existing_body=$(mktemp "${TMPDIR:-/tmp}/finding-existing.XXXXXX")
  duplicate_body=$(mktemp "${TMPDIR:-/tmp}/finding-duplicate.XXXXXX")

  cat >"$existing_body" <<'EOF'
## [FINDING-ID] Hardcoded testing credentials exposed in client bundle
- **Discovered by**: source-analyzer
- **Severity**: HIGH
- **OWASP Category**: A07:2021 Identification and Authentication Failures
- **Type**: Hardcoded Credential Exposure
- **Parameter**: `testingUsername` / `testingPassword` in `downloads/main.js`
- **Evidence**: `downloads/main.js:621` contains `testingUsername="testing@juice-sh.op";testingPassword="IamUsedForTesting"` inside the login component.
EOF

  cat >"$duplicate_body" <<'EOF'
## [FINDING-ID] Publicly exposed client-side testing credentials
- **Discovered by**: source-analyzer
- **Severity**: MEDIUM
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Hardcoded Credential Exposure
- **Parameter**: `testingUsername` / `testingPassword` in `main.js`
- **Evidence**: Public client bundle contains `testingUsername="testing@juice-sh.op"; testingPassword="IamUsedForTesting"` at `downloads/main.js:621`
EOF

  appended_id=$("$APPEND_SCRIPT" "$dir" source-analyzer "$existing_body")
  duplicate_id=$("$APPEND_SCRIPT" "$dir" source-analyzer "$duplicate_body")

  [[ "$appended_id" == "FINDING-SA-001" ]] || fail "expected FINDING-SA-001, got $appended_id"
  [[ "$duplicate_id" == "FINDING-SA-001" ]] || fail "expected duplicate artifact evidence append to reuse FINDING-SA-001, got $duplicate_id"

  count=$(rg -c '^## \[FINDING-SA-' "$dir/findings.md")
  [[ "$count" == "1" ]] || fail "expected duplicate artifact evidence to be skipped, got $count findings"
  rg 'Finding Count.*1' "$dir/findings.md" >/dev/null || fail "finding count not updated to 1"

  rm -f "$existing_body" "$duplicate_body"
  rm -rf "$dir"
}

test_integrity_check_detects_duplicate_artifact_evidence() {
  local dir out
  dir=$(make_engagement_dir)
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 2

## [FINDING-SA-001] Hardcoded testing credentials exposed in client bundle
- **Severity**: HIGH
- **OWASP Category**: A07:2021 Identification and Authentication Failures
- **Type**: Hardcoded Credential Exposure
- **Parameter**: `testingUsername` / `testingPassword` in `downloads/main.js`
- **Evidence**: `downloads/main.js:621` contains `testingUsername="testing@juice-sh.op";testingPassword="IamUsedForTesting"` inside the login component.

## [FINDING-SA-002] Publicly exposed client-side testing credentials
- **Severity**: MEDIUM
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Hardcoded Credential Exposure
- **Parameter**: `testingUsername` / `testingPassword` in `main.js`
- **Evidence**: Public client bundle contains `testingUsername="testing@juice-sh.op"; testingPassword="IamUsedForTesting"` at `downloads/main.js:621`
EOF

  out=$(mktemp "${TMPDIR:-/tmp}/finding-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    fail "integrity check should fail on duplicate artifact evidence"
  fi
  rg 'Duplicate finding signatures' "$out" >/dev/null || fail "missing duplicate artifact signature failure output"
  rg 'downloads/main\.js:621' "$out" >/dev/null || fail "missing duplicate artifact reference in integrity output"

  rm -f "$out"
  rm -rf "$dir"
}

test_append_reuses_existing_id_for_reordered_multi_route_duplicates() {
  local dir existing_body duplicate_body appended_id duplicate_id count
  dir=$(make_engagement_dir)
  existing_body=$(mktemp "${TMPDIR:-/tmp}/finding-existing.XXXXXX")
  duplicate_body=$(mktemp "${TMPDIR:-/tmp}/finding-duplicate.XXXXXX")

  cat >"$existing_body" <<'EOF'
## [FINDING-ID] Unauthenticated access to admin configuration endpoints
- **Discovered by**: vulnerability-analyst
- **Severity**: MEDIUM
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Missing Authentication / Administrative Information Disclosure
- **Parameter**: `GET /rest/admin/application-configuration` and `GET /rest/admin/application-version`
EOF

  cat >"$duplicate_body" <<'EOF'
## [FINDING-ID] Missing authentication on admin configuration endpoints
- **Discovered by**: vulnerability-analyst
- **Severity**: MEDIUM
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Missing Authentication / Information Disclosure
- **Parameter**: `GET /rest/admin/application-version`, `GET /rest/admin/application-configuration`
EOF

  appended_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$existing_body")
  duplicate_id=$("$APPEND_SCRIPT" "$dir" vulnerability-analyst "$duplicate_body")

  [[ "$appended_id" == "FINDING-VA-001" ]] || fail "expected FINDING-VA-001, got $appended_id"
  [[ "$duplicate_id" == "FINDING-VA-001" ]] || fail "expected reordered route duplicate to reuse FINDING-VA-001, got $duplicate_id"

  count=$(rg -c '^## \[FINDING-VA-' "$dir/findings.md")
  [[ "$count" == "1" ]] || fail "expected reordered route duplicate to be skipped, got $count findings"

  rm -f "$existing_body" "$duplicate_body"
  rm -rf "$dir"
}

test_append_reuses_existing_id_for_same_route_similar_title_even_when_severity_differs() {
  local dir existing_body duplicate_body appended_id duplicate_id count
  dir=$(make_engagement_dir)
  existing_body=$(mktemp "${TMPDIR:-/tmp}/finding-existing.XXXXXX")
  duplicate_body=$(mktemp "${TMPDIR:-/tmp}/finding-duplicate.XXXXXX")

  cat >"$existing_body" <<'EOF'
## [FINDING-ID] Public /ftp directory listing exposes backup and sensitive artifact downloads
- **Discovered by**: source-analyzer
- **Severity**: MEDIUM
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Directory Listing / Sensitive File Exposure
- **Parameter**: `GET /ftp`
EOF

  cat >"$duplicate_body" <<'EOF'
## [FINDING-ID] Public FTP directory listing exposes backup and sensitive artifacts
- **Discovered by**: source-analyzer
- **Severity**: HIGH
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Directory Listing / Sensitive File Exposure
- **Parameter**: `GET /ftp`
EOF

  appended_id=$("$APPEND_SCRIPT" "$dir" source-analyzer "$existing_body")
  duplicate_id=$("$APPEND_SCRIPT" "$dir" source-analyzer "$duplicate_body")

  [[ "$appended_id" == "FINDING-SA-001" ]] || fail "expected FINDING-SA-001, got $appended_id"
  [[ "$duplicate_id" == "FINDING-SA-001" ]] || fail "expected same-route similar-title duplicate to reuse FINDING-SA-001, got $duplicate_id"

  count=$(rg -c '^## \[FINDING-SA-' "$dir/findings.md")
  [[ "$count" == "1" ]] || fail "expected same-route similar-title duplicate to be skipped, got $count findings"

  rm -f "$existing_body" "$duplicate_body"
  rm -rf "$dir"
}

test_integrity_check_detects_reordered_route_and_same_route_duplicates() {
  local dir out
  dir=$(make_engagement_dir)
  cat >"$dir/findings.md" <<'EOF'
# Findings

- **Finding Count**: 3

## [FINDING-VA-001] Unauthenticated access to admin configuration endpoints
- **Severity**: MEDIUM
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Missing Authentication / Administrative Information Disclosure
- **Parameter**: `GET /rest/admin/application-configuration` and `GET /rest/admin/application-version`

## [FINDING-VA-002] Missing authentication on admin configuration endpoints
- **Severity**: MEDIUM
- **OWASP Category**: A01:2021 Broken Access Control
- **Type**: Missing Authentication / Information Disclosure
- **Parameter**: `GET /rest/admin/application-version`, `GET /rest/admin/application-configuration`

## [FINDING-SA-001] Public /ftp directory listing exposes backup and sensitive artifact downloads
- **Severity**: MEDIUM
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Directory Listing / Sensitive File Exposure
- **Parameter**: `GET /ftp`

## [FINDING-SA-002] Public FTP directory listing exposes backup and sensitive artifacts
- **Severity**: HIGH
- **OWASP Category**: A05:2021 Security Misconfiguration
- **Type**: Directory Listing / Sensitive File Exposure
- **Parameter**: `GET /ftp`
EOF

  out=$(mktemp "${TMPDIR:-/tmp}/finding-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    fail "integrity check should fail on reordered-route and same-route duplicates"
  fi
  rg 'reason=route\+owasp\+severity\+type-bucket' "$out" >/dev/null || fail "missing route+severity+type-bucket duplicate reason"
  rg 'reason=route\+owasp\+title-similarity' "$out" >/dev/null || fail "missing route+title-similarity duplicate reason"
  rg '/rest/admin/application-configuration' "$out" >/dev/null || fail "missing admin route in integrity output"
  rg 'route=/ftp' "$out" >/dev/null || fail "missing /ftp route in integrity output"

  rm -f "$out"
  rm -rf "$dir"
}

main() {
  need_script "$ALLOCATE_SCRIPT"
  need_script "$APPEND_SCRIPT"
  need_script "$CHECK_SCRIPT"
  test_allocate_next_id_uses_prefix_max
  test_integrity_check_accepts_empty_findings
  test_allocate_next_id_ignores_binary_noise
  test_append_assigns_unique_ids_under_lock
  test_append_reuses_existing_id_for_duplicate_title
  test_append_reuses_existing_id_for_duplicate_signature
  test_integrity_check_detects_duplicates_and_count_mismatch
  test_integrity_check_detects_duplicate_signatures
  test_append_reuses_existing_id_for_duplicate_artifact_evidence
  test_integrity_check_detects_duplicate_artifact_evidence
  test_append_reuses_existing_id_for_reordered_multi_route_duplicates
  test_append_reuses_existing_id_for_same_route_similar_title_even_when_severity_differs
  test_integrity_check_detects_reordered_route_and_same_route_duplicates
  echo "finding contracts: ok"
}

main "$@"
