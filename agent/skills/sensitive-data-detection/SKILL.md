---
name: sensitive-data-detection
description: Detect PII, credentials, and corporate sensitive data in API responses, source code, files, headers, and database extracts
origin: RedteamOpencode
---

# Sensitive Data Detection

## When to Activate

- API responses contain user data (JSON/XML with user objects, lists, profiles)
- Source code analysis reveals hardcoded data or config files
- File downloads (CSV, SQL dumps, backups, logs) need PII triage
- SQLi extraction results need data classification
- HTTP headers or cookies contain suspicious encoded data
- Any endpoint returns more data fields than expected

## Tools

`grep`, `rg` (ripgrep), `jq`, `curl`, `base64`, `python3`

## Detection Methodology

### Phase 1: Automated Pattern Scan

Run against any text corpus (API response, source file, database dump, downloaded file):

```bash
# Save target content to a temp file first, then scan all patterns in one pass
TARGET_FILE=$(mktemp)
trap 'rm -f "$TARGET_FILE"' EXIT

# === IDENTITY DOCUMENTS ===

# China — 18-digit ID card (with checksum digit X)
rg -oN '[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]' "$TARGET_FILE"

# US — Social Security Number
rg -oN '\b\d{3}-\d{2}-\d{4}\b' "$TARGET_FILE"

# UK — National Insurance Number
rg -oN '\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b' "$TARGET_FILE"

# Japan — My Number (12 digits)
rg -oN '\b\d{12}\b' "$TARGET_FILE"

# South Korea — Resident Registration Number
rg -oN '\b\d{6}-[1-4]\d{6}\b' "$TARGET_FILE"

# India — Aadhaar (12 digits, starts with 2-9)
rg -oN '\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b' "$TARGET_FILE"

# EU/International — Passport (common formats)
rg -oN '\b[A-Z]{1,2}\d{6,9}\b' "$TARGET_FILE"

# Brazil — CPF
rg -oN '\b\d{3}\.\d{3}\.\d{3}-\d{2}\b' "$TARGET_FILE"

# Germany — Personalausweis
rg -oN '\b[CFGHJKLMNPRTVWXYZ0-9]{9}\b' "$TARGET_FILE"

# === FINANCIAL ===

# Credit card numbers (13-19 digits, common prefixes)
rg -oN '\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))[- ]?\d{4}[- ]?\d{4}[- ]?\d{1,7}\b' "$TARGET_FILE"

# IBAN (international bank account)
rg -oN '\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b' "$TARGET_FILE"

# China — Bank card (16-19 digits, starts with 62)
rg -oN '\b62\d{14,17}\b' "$TARGET_FILE"

# Bitcoin address
rg -oN '\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b' "$TARGET_FILE"
rg -oN '\bbc1[a-zA-HJ-NP-Z0-9]{25,90}\b' "$TARGET_FILE"

# === CONTACT ===

# Email
rg -oN '\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b' "$TARGET_FILE"

# Phone — international with country code
rg -oN '\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}' "$TARGET_FILE"

# Phone — China mobile (11 digits starting with 1)
rg -oN '\b1[3-9]\d{9}\b' "$TARGET_FILE"

# Phone — US (10 digits)
rg -oN '\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b' "$TARGET_FILE"

# Phone — Japan
rg -oN '\b0[789]0-\d{4}-\d{4}\b' "$TARGET_FILE"

# Physical address patterns (street number + name)
rg -oN '\b\d{1,5}\s[A-Z][a-z]+\s(St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pl)\b' "$TARGET_FILE"

# === CREDENTIALS & SECRETS ===

# API keys (high entropy strings)
rg -oN '(?i)(api[_-]?key|apikey|api[_-]?secret|access[_-]?key)["\s:=]+["\x27]?[A-Za-z0-9/+=_-]{20,}' "$TARGET_FILE"

# AWS keys
rg -oN '\bAKIA[A-Z0-9]{16}\b' "$TARGET_FILE"
rg -oN '(?i)(aws[_-]?secret|secret[_-]?key)["\s:=]+["\x27]?[A-Za-z0-9/+=]{40}' "$TARGET_FILE"

# Azure / GCP
rg -oN '(?i)(azure|subscription)[_-]?(id|key|secret|token)["\s:=]+["\x27]?[A-Za-z0-9/+=_-]{20,}' "$TARGET_FILE"
rg -oN '\bAIza[A-Za-z0-9_-]{35}\b' "$TARGET_FILE"

# JWT tokens
rg -oN '\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' "$TARGET_FILE"

# Private keys
rg -oN '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----' "$TARGET_FILE"

# Generic password patterns
rg -oN '(?i)(password|passwd|pwd|pass)["\s:=]+["\x27]?[^\s"'\'']{4,}' "$TARGET_FILE"

# Bearer tokens
rg -oN '(?i)bearer\s+[A-Za-z0-9_.-]{20,}' "$TARGET_FILE"

# Database connection strings
rg -oN '(?i)(mysql|postgres|mongodb|redis|mssql)://[^\s"<>]+' "$TARGET_FILE"

# Webhook URLs (Slack, Discord, etc)
rg -oN 'https://hooks\.(slack|discord)\.com/[^\s"<>]+' "$TARGET_FILE"

# === CORPORATE INFRASTRUCTURE ===

# Internal IPs (RFC1918)
rg -oN '\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b' "$TARGET_FILE"

# Internal hostnames
rg -oN '(?i)\b[a-z0-9-]+\.(internal|local|corp|intranet|private|lan)\b' "$TARGET_FILE"

# AWS Account ID (12 digits)
rg -oN '\b\d{12}\b' "$TARGET_FILE"

# S3 bucket names
rg -oN '(?i)(s3://|s3\.amazonaws\.com/|\.s3\.)[a-z0-9.-]+' "$TARGET_FILE"

# Docker registry
rg -oN '(?i)\b[a-z0-9.-]+\.(azurecr\.io|gcr\.io|ecr\.[a-z-]+\.amazonaws\.com)/[^\s"]+' "$TARGET_FILE"

# === MEDICAL (HIPAA) ===

# ICD codes (diagnosis)
rg -oN '\b[A-Z]\d{2}(\.\d{1,4})?\b' "$TARGET_FILE"

# US Medicare/Medicaid ID
rg -oN '\b\d{10}[A-Z]\b' "$TARGET_FILE"

# DEA number (prescriber)
rg -oN '\b[ABCDFGHMJKLPT][A-Z9]\d{7}\b' "$TARGET_FILE"
```

### Phase 2: JSON Field Name Analysis

For API responses, scan field names for sensitive data indicators:

```bash
# Extract all JSON keys and check against sensitive patterns
echo "$RESPONSE" | jq -r '[paths(scalars)] | .[] | join(".")' | \
  rg -i '(ssn|social.?security|tax.?id|national.?id|identity|passport|license|permit|
          card.?num|cvv|expir|account.?num|routing|iban|swift|
          password|secret|token|key|hash|salt|credential|
          phone|mobile|cell|fax|tel|
          email|mail|
          birth|dob|age|gender|sex|race|ethnic|religion|
          salary|income|wage|compensation|
          address|street|city|zip|postal|
          diagnosis|medical|health|prescription|allergy|blood|
          biometric|fingerprint|face.?id|iris|
          employee.?id|staff.?id|badge|department|manager|
          customer.?id|member.?id|subscriber|
          latitude|longitude|geo|location|ip.?addr)'
```

### Phase 3: Authenticated Privileged Data Sweep

When an engagement obtains an admin token, forged JWT, recovered session, or any other privileged auth context, immediately sweep sensitive-data endpoints before returning to generic queue work. Do not leave these as low-priority queued cases after an admin takeover chain.

CTF/Juice Shop recall contract:
- After forged/admin JWT proof, request and classify `/rest/user/authentication-details/`, `/api/Users`, `/api/Users/<id>`, `/rest/admin/application-configuration`, backup files under `/ftp`, and any discovered `user/authentication` route with the privileged token.
- Treat fields named `password`, `passwordHash`, `hash`, `salt`, `email`, `role`, `totpSecret`, `securityAnswer`, `apiKey`, or `credential` as sensitive findings even when the endpoint is expected to be admin-only; record the exact endpoint and first affected user/hash prefix as challenge evidence.
- For Juice Shop `User Credentials` recall, do not stop at the generic roster finding. Preserve
  one artifact that demonstrates credential-bearing material specifically (for example
  `/rest/user/authentication-details/`, `/api/Users`, or a database/backup response containing
  password hashes, salts, security answers, TOTP secrets, or credential fields), then check
  solved-state evidence. If only emails/roles were captured and credential-bearing fields remain
  queued, return `REQUEUE` with the exact endpoint and auth context needed to finish the branch.
- If an admin/JWT exploit confirms access but sensitive-data endpoints remain queued or untested, requeue a narrowed follow-up instead of marking the chain done. This preserves recall for password-hash/user-credential leak challenges that otherwise regress when exploitation stops at “admin access confirmed.”

### Phase 4: HTTP Header & Cookie Inspection

```bash
# Check response headers for leaked info
run_tool curl -sI "$TARGET_URL" | rg -i '(x-user|x-customer|x-employee|x-account|x-session|x-token|x-debug|x-internal|x-forwarded-for|x-real-ip)'

# Decode and inspect cookies
run_tool curl -s -c - "$TARGET_URL" | while read -r line; do
  cookie_val=$(echo "$line" | awk '{print $NF}')
  # Try base64 decode
  decoded=$(echo "$cookie_val" | base64 -d 2>/dev/null)
  if [ -n "$decoded" ]; then
    echo "[cookie:b64] $decoded"
  fi
  # Try URL decode
  echo "$cookie_val" | python3 -c "import sys,urllib.parse; print(urllib.parse.unquote(sys.stdin.read()))" 2>/dev/null
done
```

### Phase 4: File Content Classification

For downloaded files (CSV, SQL dumps, logs, backups):

```bash
# Detect file type and choose scan strategy
FILE_TYPE=$(file -b "$DOWNLOADED_FILE")
case "$FILE_TYPE" in
  *CSV*|*comma*)
    # Extract header row, check for PII column names
    head -1 "$DOWNLOADED_FILE" | tr ',' '\n' | \
      rg -i '(name|email|phone|ssn|address|dob|birth|salary|card|account|password)'
    ;;
  *SQL*)
    # Look for INSERT statements with PII patterns
    rg -i 'INSERT INTO.*(user|customer|employee|patient|member)' "$DOWNLOADED_FILE" | head -5
    # Look for CREATE TABLE with sensitive columns
    rg -i 'CREATE TABLE' "$DOWNLOADED_FILE" -A 20 | \
      rg -i '(ssn|password|phone|email|address|salary|card_num|dob|birth)'
    ;;
  *JSON*)
    # Run Phase 2 field name analysis
    jq -r '[paths(scalars)] | .[] | join(".")' "$DOWNLOADED_FILE" | \
      rg -i '(ssn|password|phone|email|address|salary|card|birth|token|secret)'
    ;;
  *XML*|*HTML*)
    rg -i '(<password|<ssn|<email|<phone|<address|<credit|<token|<secret)' "$DOWNLOADED_FILE"
    ;;
esac
```

### Phase 5: Database Extract Classification

After SQLi extraction, classify the data:

```bash
# For each extracted column, sample values and detect type
# Run Phase 1 patterns against extracted data
# Additionally check for:

# MD5 hashes (likely password hashes)
rg -oN '\b[a-f0-9]{32}\b' "$EXTRACT_FILE"

# SHA-256 hashes
rg -oN '\b[a-f0-9]{64}\b' "$EXTRACT_FILE"

# bcrypt hashes
rg -oN '\$2[aby]?\$\d{2}\$[./A-Za-z0-9]{53}' "$EXTRACT_FILE"

# Base64-encoded blobs (may contain PII)
rg -oN '\b[A-Za-z0-9+/]{40,}={0,2}\b' "$EXTRACT_FILE"
```

### Phase 6: CTF / Juice Shop Recall Sweep

When the target is a local CTF benchmark or artifacts identify OWASP Juice Shop, public file and data exposures are not finished after the first sensitive-data finding. Before marking the case done, run one bounded recall sweep that converts exposed artifacts into challenge-triggering evidence:

- For `/ftp` listings, direct-download and inspect exact challenge files and backups that are commonly solved by access itself or by extracting a secret: `acquisitions.md`, `package.json.bak`, `package-lock.json.bak`, KeePass/SQLite/zip backups, quarantine shortcut `.url` files, and any document whose name suggests confidential, support, incident, credential, or backup material.
- Preserve Juice Shop artifact-to-challenge coverage explicitly. The recall sweep must name and check these solved-state targets before closing a public-file exposure: `Deprecated Interface` (`package.json.bak` / `package-lock.json.bak`), `Easter Egg` and `Nested Easter Egg` (easter-egg route or hidden media/file references), `Forgotten Developer Backup`, `Forgotten Sales Backup`, `Misplaced Signature File`, `Exposed Metrics`, `Poison Null Byte`, and `NFT Takeover` when Web3/NFT artifacts or routes are discovered.
- If `package.json.bak`, `package-lock.json.bak`, signature/backup files, or other Juice Shop `/ftp` artifacts return 403/blocked, immediately preserve a narrowed bypass follow-up instead of treating the carrier as done. Include exact candidates such as `%2500.md` poison-null-byte suffixes, adjacent `.sig` files, backup filenames from the listing, and the concrete `/metrics` route when it was discovered. This protects `Deprecated Interface`, `Forgotten Developer Backup`, `Forgotten Sales Backup`, `Misplaced Signature File`, `Poison Null Byte`, and `Exposed Metrics` from regressing when the first direct artifact request is blocked.
- For Web3/NFT discoveries, do not stop at the first authenticated route or sandbox proof. Preserve a concrete follow-up for the NFT/contract artifact or route consumer and verify solved-state for `NFT Takeover` separately from generic Web3 access.
- For API or database responses containing `password`, `hash`, `email`, `role`, `securityAnswer`, `totp`, `deluxeToken`, or JWT claim material, run the hash/secret scan above and preserve a narrowed follow-up for the consumer workflow instead of closing on a generic exposure note.
- After each bounded artifact access, blocked-artifact bypass, or extraction, check challenge solved-state evidence (`/api/Challenges` or the Score Board route) and record the challenge name when it changes. If the named challenge remains unsolved, requeue the exact artifact, route, or consumer action still needed; when a bypass is the concrete next step, requeue the exact artifact, route, bypass, or consumer action. If the file is blocked, requeue the exact blocked path with the HTTP status/body clue and the next bypass candidate. Do not collapse it into a broad `/ftp` duplicate.
- Treat the named recall targets as a closure checklist, not as examples. Before reporting, the handoff must explicitly account for each discovered candidate in this exact form: `challenge=<name> status=solved|blocked|requeued evidence=<path or response> next=<exact concrete action>`. This is mandatory for the recent regression set `Exposed Metrics`, `Exposed credentials`, `NFT Takeover`, `Forged Feedback`, `Easter Egg`, and `Forgotten Sales Backup` whenever their artifacts, endpoints, or adjacent carriers appear in the run. A generic phrase such as "ftp artifact closure", "metrics checked", or "Web3 route inspected" is not sufficient.
- If `/metrics`, credential-bearing API/database responses, NFT/Web3 routes, feedback/order APIs, easter-egg/media references, or sales/developer backup filenames are observed but the matching named challenge remains unsolved, emit `REQUEUE` with the exact path or workflow as the next case instead of `DONE STAGE=exhausted`. Prefer a narrowed sibling follow-up (`/metrics`, `/ftp/<backup>%2500.md`, the NFT route/contract artifact, or the specific feedback/order request) over a broad duplicate `/ftp` or generic data-exposure case.
- When validated credentials land, do not treat auth respawn as bookkeeping separate from recall. The next authenticated recon/source refresh must carry this same named recall checklist, and the first post-auth queue pass must pull at least one exact recall candidate from the regression set before returning to generic backlog.
- Keep these follow-ups separate from the initial disclosure finding: a public KeePass vault or backup finding can be valid while Password Hash Leak, Deprecated Interface, Forgotten backups, Confidential Document, Exposed Metrics, Exposed credentials, NFT Takeover, Forged Feedback, Easter Egg, or other low-difficulty recall triggers still need an exact artifact/action pass.

## Luhn Checksum Validation

For suspected credit card numbers, validate before reporting:

```bash
# Python one-liner for Luhn validation
python3 -c "
import sys
n = sys.argv[1].replace('-','').replace(' ','')
if not n.isdigit(): sys.exit(1)
digits = [int(d) for d in n]
odd_digits = digits[-1::-2]
even_digits = digits[-2::-2]
total = sum(odd_digits) + sum(sum(divmod(2*d, 10)) for d in even_digits)
sys.exit(0 if total % 10 == 0 else 1)
" "$CARD_NUMBER" && echo "VALID" || echo "INVALID"
```

## Severity Classification

| Data Type | Severity | Rationale |
|-----------|----------|-----------|
| Credentials (passwords, keys, tokens) | CRITICAL | Direct system access |
| Credit card / bank account | CRITICAL | Financial fraud |
| Identity documents (SSN, national ID, passport) | CRITICAL | Identity theft |
| Private keys / certificates | CRITICAL | Infrastructure compromise |
| Medical records (HIPAA) | HIGH | Regulatory + personal harm |
| Database connection strings | HIGH | Infrastructure access |
| Internal IPs / hostnames | HIGH | Lateral movement |
| Phone numbers + email | MEDIUM | Social engineering |
| Physical addresses | MEDIUM | Privacy violation |
| Employee IDs / org structure | MEDIUM | Internal reconnaissance |
| Names / usernames | LOW | Context for other findings |
| Gender / age / preferences | LOW | Privacy concern |

## Output Format

When PII or sensitive data is detected, report as:

```markdown
#### Sensitive Data Detected
| Type | Value (truncated) | Location | Severity | Count |
|------|-------------------|----------|----------|-------|
| Credit Card (Visa) | 4532****1234 | /api/Users response | CRITICAL | 3 |
| Email Address | a***@example.com | /rest/memories | MEDIUM | 42 |
| Password Hash (MD5) | 0192023a7b... | SQLi extraction | CRITICAL | 42 |
| Internal IP | 10.0.*.* | JS config object | HIGH | 2 |
| AWS Key | AKIA****WXYZ | .env in FTP backup | CRITICAL | 1 |

**Truncation rules**: Always truncate sensitive values in output.
- Credit cards: show first 4 + last 4, mask middle
- Emails: show first char + domain
- Passwords: show first 8 chars of hash
- IDs: show first 4 + last 2, mask middle
- Keys: show prefix + last 4 chars
```

## Priority Order

1. Credentials and keys (immediate access risk)
2. Financial data with valid Luhn (provable exposure)
3. Identity documents (regulatory and legal exposure)
4. Infrastructure details (attack surface expansion)
5. Medical / biometric data (compliance risk)
6. Contact information in bulk (social engineering enabler)
7. Individual PII fields (privacy concern)

## Integration with intel.md

Detected PII feeds into intel.md:
- Email addresses → intel.md Email Addresses table
- People names + roles → intel.md People & Organizations table
- Internal IPs / domains → intel.md Domains & Infrastructure table
- Credentials → intel.md Credentials & Secrets table
- Bulk PII exposure → findings.md as separate finding with severity per table above
