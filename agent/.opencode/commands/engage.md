# Command: Engage Target

You are the operator. Execute steps ONE AT A TIME. After each step, IMMEDIATELY proceed to the next.

**Mode detection from arguments:**
- `--auto` flag present → **AUTONOMOUS MODE**: zero interaction, auto-decide everything, never ask user, never stop. If something fails, log and move on.
- No `--auto` flag → **INTERACTIVE MODE**: ask for auth setup, use numbered choices, auto-confirm phases by default.

Parse the target from user arguments at the bottom of this template.

## Step 1: Parse Target

Extract: URL, hostname, port (default 80/443), protocol (http/https).
Also check for `--auto` and `--parallel N` flags.

**Target type:**
- IP address or specific subdomain → **SINGLE TARGET** → Step 2
- Wildcard `*` or bare domain → **WILDCARD** → see Appendix A at bottom

**→ NEXT: Step 2**

## Step 2: Create Engagement Directory

```bash
TARGET="<url>" HOST="<hostname>" PORT=<port> PROTO="<scheme>" \
DIR="engagements/$(date +%Y-%m-%d)-$(date +%H%M%S)-<hostname>" \
ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ) && \
mkdir -p "$DIR"/{tools,downloads,scans,pids} && echo "$DIR"
```

Save `$DIR` — needed for ALL subsequent steps.

**→ NEXT: Step 3**

## Step 3: Initialize Files

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
cp scripts/templates/intel.md "$DIR/intel.md"
```

If template doesn't exist, create intel.md with empty Intelligence Collection tables.

**→ NEXT: Step 4**

## Step 4: Connectivity + Docker Check

```bash
curl -s -o /dev/null -w "HTTP %{http_code} | %{size_download} bytes | %{time_total}s" "$TARGET"
```

If target unreachable: STOP.

**AUTONOMOUS**: skip Docker validation — errors show naturally.
**INTERACTIVE**: also run `source scripts/lib/container.sh && check_docker && check_images`.

**→ NEXT: Step 5**

## Step 5: Configure Authentication

**AUTONOMOUS**:
- If `auth.json` has a token from prior session → use it
- Otherwise → start unauthenticated, but actively seek auth during engagement:
  - Registration endpoint found → auto-register, save creds
  - Hardcoded credentials found → auto-login, save token
  - After obtaining auth → POST-AUTH RE-COLLECTION automatically

**INTERACTIVE**:
```
Authentication setup:
  1 — Proxy login (captures real session)
  2 — Paste cookie
  3 — Paste auth header
  4 — Skip (unauthenticated only)
Reply (1-4):
```

**→ NEXT: Step 6**

## Step 6: Execute 5-Phase Engagement

Follow operator Phase Flow rules. Both modes run the same phases:

1. **RECON** — dispatch recon-specialist + source-analyzer in parallel
2. **COLLECT** — `recon_ingest.sh`, start Katana, show stats
3. **CONSUME & TEST** — dispatcher loop until pending=0
4. **EXPLOIT** — dispatch osint-analyst + exploit-developer in parallel
5. **REPORT** — dispatch report-writer, update scope.json status=completed

After each phase: update scope.json `phases_completed` and `current_phase`.

**AUTONOMOUS differences during execution:**
- Never ask for approval at phase transitions
- Always parallel dispatch
- If FUZZER_NEEDED → dispatch fuzzer automatically
- Errors → log and continue, never stop
- Progress display after every batch:
```
Phases: [x] Recon  [x] Collect  [>] Test  [ ] Exploit  [ ] Report
[queue] 120/495 done (24%) | findings: 5
```

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
