# Command: Engage Target

You are the operator initiating a new red team engagement. The user has provided a target URL/IP as arguments below this template. Follow these steps exactly:

**Mode detection from arguments:**
- `--auto` flag present → **AUTONOMOUS MODE**: zero interaction, auto-decide everything, never ask user, never stop. If something fails, log and move on.
- No `--auto` flag → **INTERACTIVE MODE**: ask for auth setup, use numbered choices, auto-confirm phases by default.

## Step 1: Parse Target

Extract the target URL from the user's arguments appended after this template. Identify:
- Full URL (scheme, host, port, path)
- Hostname (for directory naming and scope derivation)
- Port (default 80/443 if not specified)
- Optional flags: `--auto`, `--parallel N` (default 3)

If no target is provided in the arguments, ask the user for one before proceeding.

**Target type:**
- IP address or specific subdomain → **SINGLE TARGET** → Step 2
- Wildcard `*` or bare domain → **WILDCARD** → see Appendix A at bottom

## Step 2: Create Engagement Directory and Files

**IMPORTANT: Use a SINGLE bash command block to create ALL engagement files. Do NOT split into multiple tool calls — this prevents hanging between calls.**

**CRITICAL: Do NOT use single-quoted heredoc delimiters (like `<< 'SCOPE'`). Use unquoted delimiters (like `<< EOF`) so that `$VARIABLE` expands.**

Compute all values FIRST as shell variables, then write files using those variables:

```bash
# Compute values first
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M%S)
HOSTNAME_CLEAN="<hostname with special chars replaced>"
TARGET="<full target URL>"
HOSTNAME_RAW="<original hostname>"
PORT=<port number>
PROTO="<http or https>"
START_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

DIR="engagements/${DATE}-${TIME}-${HOSTNAME_CLEAN}"
mkdir -p "$DIR/tools" "$DIR/downloads" "$DIR/scans" "$DIR/pids"

cat > "$DIR/scope.json" << EOF
{
  "target": "${TARGET}",
  "hostname": "${HOSTNAME_RAW}",
  "port": ${PORT},
  "protocol": "${PROTO}",
  "mode": "single",
  "confirm_mode": "auto",
  "status": "in_progress",
  "current_phase": "recon",
  "phases_completed": [],
  "started_at": "${START_TIME}"
}
EOF

sqlite3 "$DIR/cases.db" < scripts/schema.sql

cat > "$DIR/log.md" << EOF
# Engagement Log — ${TARGET}
## ${START_TIME} — Engagement initialized
- Target: ${TARGET}
- Mode: single target
EOF

cat > "$DIR/findings.md" << EOF
# Findings — ${TARGET}
EOF

echo "{}" > "$DIR/auth.json"

cp scripts/templates/intel.md "$DIR/intel.md" 2>/dev/null || cat > "$DIR/intel.md" << 'INTELEOF'
# Intelligence Collection

## Technology Stack
| Component | Version | Source | Confidence |
|-----------|---------|--------|------------|

## People & Organizations
| Name | Role/Context | Source | Notes |
|------|-------------|--------|-------|

## Email Addresses
| Email | Source | Notes |
|-------|--------|-------|

## Domains & Infrastructure
| Item | Type | Source | Notes |
|------|------|--------|-------|

## Credentials & Secrets
| Type | Value (truncated) | Source | Notes |
|------|-------------------|--------|-------|

## Raw OSINT

### CVE & Known Vulnerabilities
| CVE | Affected | CVSS | PoC Available | Source |
|-----|----------|------|---------------|--------|

### Breach & Leak Data
| Email/Domain | Breach | Date | Data Types | Source |
|-------------|--------|------|------------|--------|

### DNS & Certificate History
| Record | Value | First Seen | Last Seen | Source |
|--------|-------|------------|-----------|--------|

### Social & OSINT Profiles
| Person/Org | Platform | URL/Handle | Notes |
|-----------|----------|------------|-------|
INTELEOF

echo "$DIR"
```

Replace all `<placeholder>` comments above with actual parsed values from Step 1.

## Step 3: Docker Environment Check

All pentest tools run in Docker containers. Check prerequisites:

```bash
source scripts/lib/container.sh

echo "=== Docker Check ==="
check_docker

echo "=== Image Check ==="
check_images

echo "=== Local Tools ==="
for tool in curl jq sqlite3 docker; do
  if which "$tool" >/dev/null 2>&1; then
    echo "[OK] $tool"
  else
    echo "[MISSING] $tool"
  fi
done
```

If images are missing, tell the user:
"Docker images not built yet. Run: `cd docker && docker compose build`"

If Docker is not installed, the engagement CANNOT proceed.

**AUTONOMOUS**: skip this check — errors show naturally in later steps.

## Step 4: Configure Authentication

**AUTONOMOUS**:
- If `auth.json` has a token → use it
- Otherwise → start unauthenticated. Operator Credential Auto-Use rules apply during engagement.

**INTERACTIVE**:
Present to user:
```
Authentication setup:
  1 — Proxy login (recommended: captures real session)
  2 — Paste cookie
  3 — Paste auth header
  4 — Skip (unauthenticated only)
Reply (1-4):
```

Wait for user response. Handle:
- `1` → tell user to run `/proxy start` then login in browser
- `2` → ask user to paste cookie string, then run `/auth cookie "<value>"`
- `3` → ask user to paste header, then run `/auth header "<value>"`
- `4` → skip auth, proceed immediately

**If user chooses 4 (skip):** Authentication is skipped but ALL subsequent steps still
execute normally. The user can configure auth later at any time with `/auth`.

## Step 5: Begin Operator Core Loop

Initialization complete. Now follow the **operator prompt** Phase Flow (RECON → COLLECT → TEST → EXPLOIT → REPORT) and Core Loop rules.

**AUTONOMOUS**: never ask approval, always parallel, errors → log and continue.
**INTERACTIVE**: auto-confirm by default, ask for first phase approval.

---

## Appendix A: Wildcard Mode

Only read this section if Step 1 detected wildcard mode.

### Phase 0: Enumerate Subdomains

```bash
DOMAIN="<root domain>"
PARENT_DIR="engagements/$(date +%Y-%m-%d)-$(date +%H%M%S)-wildcard-${DOMAIN//\./-}"
mkdir -p "$PARENT_DIR/scans"
source scripts/lib/container.sh && export ENGAGEMENT_DIR="$PARENT_DIR"
run_tool subfinder -d "$DOMAIN" -all -silent -o /engagement/scans/subdomains_raw.txt
```

Then follow subdomain-enumeration skill for 3-stage filter (DNS → web port → fingerprint).

### Phase 0.5: Prioritize

**INTERACTIVE**: Present prioritized list, get approval.
**AUTONOMOUS**: Announce order, immediately start.

### Phase 0.9: Sliding Window

Process max N subdomains in parallel (default 3). Each runs full 5-phase flow.
When one completes → start next. NEVER create all directories upfront.

WAF gate check before each: skip if 403 + Cloudflare/CloudFront challenge.

### Phase FINAL: Consolidated Report

Merge all child findings.md into parent report.md.

---

## User Arguments

The target and any additional context from the user follows:
