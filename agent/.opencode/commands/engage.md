# Command: Engage Target

You are the operator. Execute these steps ONE AT A TIME. After each step, IMMEDIATELY proceed to the next.

Parse the target from user arguments below this template. If no target provided, ask for one.

## Step 1: Parse Target

Extract: URL, hostname, port (default 80/443), protocol (http/https).

**Mode detection:**
- IP address or specific subdomain (e.g., `http://127.0.0.1:8000`, `http://app.test.com`) → **SINGLE TARGET** → Step 2
- Wildcard `*` or bare domain (e.g., `http://*.test.com`, `http://test.com`) → **WILDCARD** → see Appendix A at bottom

## Step 2: Create Engagement Directory

Run this bash command (replace placeholders with parsed values):

```bash
TARGET="<url>" HOST="<hostname>" PORT=<port> PROTO="<scheme>" \
DIR="engagements/$(date +%Y-%m-%d)-$(date +%H%M%S)-<hostname>" \
ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ) && \
mkdir -p "$DIR"/{tools,downloads,scans,pids} && echo "$DIR"
```

Save the `$DIR` value — you need it for ALL subsequent steps.

**→ NEXT: Step 3**

## Step 3: Initialize Engagement Files

Run FOUR separate bash commands. Do NOT combine them.

**3a — scope.json:**
```bash
cat > "$DIR/scope.json" << EOF
{"target":"$TARGET","hostname":"$HOST","port":$PORT,"protocol":"$PROTO","mode":"single","confirm_mode":"auto","status":"in_progress","current_phase":"recon","phases_completed":[],"started_at":"$ISO"}
EOF
```

**3b — cases.db:**
```bash
sqlite3 "$DIR/cases.db" < scripts/schema.sql
```

**3c — log.md + findings.md + auth.json:**
```bash
echo "# Engagement Log — $TARGET" > "$DIR/log.md"
echo "# Findings — $TARGET" > "$DIR/findings.md"
echo "{}" > "$DIR/auth.json"
```

**3d — intel.md:**
```bash
cat > "$DIR/intel.md" << 'INTELEOF'
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
```

**→ NEXT: Step 4**

## Step 4: Docker Check

```bash
source scripts/lib/container.sh && check_docker && check_images && echo "[OK] Docker ready"
```

If images missing: tell user to run `cd docker && docker compose build`. If Docker not installed: STOP.

**→ NEXT: Step 5**

## Step 5: Configure Authentication

Present to user:
```
Authentication setup:
  1 — Proxy login (captures real session)
  2 — Paste cookie
  3 — Paste auth header
  4 — Skip (unauthenticated only)
Reply (1-4):
```

Handle response. If skip (4): proceed — all phases still execute on unauthenticated surface.

**→ NEXT: Step 6**

## Step 6: Quick Connectivity Check

```bash
curl -s -o /dev/null -w "HTTP %{http_code} | %{size_download} bytes | %{time_total}s" "$TARGET"
```

If target unreachable: STOP and report.

**→ NEXT: Step 7**

## Step 7: Begin 5-Phase Engagement

Now enter the operator core loop. Dispatch agents per your operator prompt rules:

**Phase 1: RECON** — Dispatch recon-specialist + source-analyzer in parallel.
After both complete: record findings, append Intelligence to intel.md.

**Phase 2: COLLECT** — Import endpoints: `./scripts/recon_ingest.sh "$DIR/cases.db" recon-specialist`
Start Katana: `./scripts/katana_ingest.sh "$DIR" &`
Show stats: `./scripts/dispatcher.sh "$DIR/cases.db" stats`

**Phase 3: CONSUME & TEST** — Dispatcher loop per case-dispatching skill.

**Phase 4: EXPLOIT** — Dispatch osint-analyst + exploit-developer in parallel.
After osint-analyst: read intel.md, high-value → findings.md + exploit-developer 2nd round.

**Phase 5: REPORT** — Dispatch report-writer.

After each phase: update scope.json `phases_completed` and `current_phase`.

---

## Appendix A: Wildcard Mode

Only read this section if Step 1 detected wildcard mode.

### Phase 0: Enumerate Subdomains

```bash
DOMAIN="<root domain>"
DATE=$(date +%Y-%m-%d) && TIME=$(date +%H%M%S)
PARENT_DIR="engagements/${DATE}-${TIME}-wildcard-${DOMAIN//\./-}"
mkdir -p "$PARENT_DIR/scans"

source scripts/lib/container.sh
export ENGAGEMENT_DIR="$PARENT_DIR"

run_tool subfinder -d "$DOMAIN" -all -silent -o /engagement/scans/subdomains_raw.txt
echo "Raw subdomains: $(wc -l < $PARENT_DIR/scans/subdomains_raw.txt)"
```

Then follow subdomain-enumeration skill for 3-stage filter (DNS → web port → fingerprint).

### Phase 0.5: Prioritize

Follow SUBDOMAIN PRIORITIZATION in operator.txt. Present prioritized list, get approval.

### Phase 0.9: Sliding Window

Process max 3 subdomains in parallel. Each runs the full 5-phase flow.
When one completes → start next. NEVER create all directories upfront.

WAF gate check before each subdomain:
```bash
code=$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 5 "https://$sub")
# Skip if 403 + Cloudflare/CloudFront challenge
```

### Phase FINAL: Consolidated Report

Merge all child findings.md into parent report.md.

---

## User Arguments

The target and any additional context from the user follows:
