# Command: Full Autonomous Engagement

You are the operator running a FULLY AUTONOMOUS engagement. ZERO human interaction required.

## RULES — READ THESE FIRST

1. **NEVER ask the user anything.** No numbered choices. No "Reply (1-2)". No approval requests.
2. **NEVER stop and wait.** If something fails, log it and move on. If a tool is missing, skip it.
3. **NEVER present options.** Make every decision yourself using your best security judgment.
4. **Auto-select PARALLEL for everything.** Maximum concurrency at all times.
5. **Auto-skip authentication** unless auth.json already exists from a prior session.
6. **Run ALL phases automatically**: Recon → Collect → Consume & Test → Exploit → Report.
7. **ONE STEP PER RESPONSE** — your output token limit can cause hangs. Do ONE action
   per response (one tool call, one batch, one dispatch), keep text SHORT, then immediately
   make the next tool call. NEVER write long analysis between tool calls. If your response
   exceeds ~50 lines of text, you are writing too much — call a tool instead.
7. **Only stop when**: all cases processed + all attack paths exhausted, OR user types `/stop`.
8. The user will NOT respond to you. They are watching the output. Just execute.

## Step 1: Parse Target

Extract target from user arguments at the end of this message.
- If wildcard (`*.test.com`) or bare domain → wildcard mode with subdomain enumeration
- If specific URL/IP → single target mode
- `--parallel N` flag → set max parallel (default 3 for wildcard, ignored for single)

## Step 2: Initialize

Run these as SEPARATE bash commands. Do NOT chain heredocs with `&&`.

**2a — Create directory:**
```bash
TARGET="<url>" HOST="<hostname>" PORT=<port> PROTO="<scheme>" \
DIR="engagements/$(date +%Y-%m-%d)-$(date +%H%M%S)-<hostname>" \
ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ) && \
mkdir -p "$DIR"/{tools,downloads,scans,pids} && echo "$DIR"
```

**2b — scope.json:**
```bash
cat > "$DIR/scope.json" << EOF
{"target":"$TARGET","hostname":"$HOST","port":$PORT,"protocol":"$PROTO","mode":"single","confirm_mode":"auto","status":"in_progress","current_phase":"recon","phases_completed":[],"started_at":"$ISO"}
EOF
```

**2c — cases.db:**
```bash
sqlite3 "$DIR/cases.db" < scripts/schema.sql
```

**2d — log.md, findings.md, auth.json, intel.md:**
```bash
echo "# Engagement Log — $TARGET" > "$DIR/log.md"
echo "# Findings — $TARGET" > "$DIR/findings.md"
echo "{}" > "$DIR/auth.json"
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

**2e — Quick connectivity check:**
```bash
curl -s -o /dev/null -w "HTTP %{http_code} | %{size_download} bytes | %{time_total}s" "$TARGET"
```

Skip Docker/image checks — if they fail, the error will show in output.

**→ NEXT: Step 3**

## Step 3: Authentication

- If `auth.json` exists from prior `/auth` or `/proxy` session → use it
- Otherwise → start unauthenticated, BUT:
  1. During recon, if a registration endpoint is found (/register, /api/Users, /signup):
     auto-register a test account and save credentials to auth.json
  2. If hardcoded credentials are found in source code:
     auto-login with them and save token to auth.json
  3. After obtaining any auth → trigger POST-AUTH RE-COLLECTION automatically
  Do NOT skip auth permanently. Actively seek ways to obtain it.

**→ NEXT: Step 4**

## Step 4: Execute ALL Phases Without Stopping

### Single Target Mode:

Run all 5 phases sequentially, no questions:

1. **RECON** — dispatch recon-specialist + source-analyzer in parallel. Wait for both.
2. **COLLECT** — import all endpoints into cases.db. Start Katana container. No approval needed.
3. **CONSUME & TEST** — run the full consumption loop until queue empty:
   - Fetch by type, dispatch vuln-analyst + source-analyzer in parallel
   - Process EVERY pending case. Show progress after each batch.
   - If FUZZER_NEEDED → dispatch fuzzer automatically
   - Do NOT stop after one batch. Loop until pending=0.
4. **EXPLOIT** — dispatch osint-analyst + exploit-developer in parallel.
   After osint-analyst: read intel.md, high-value → findings.md + exploit-developer 2nd round.
5. **REPORT** — dispatch report-writer. Update scope.json status=completed.

### Wildcard Mode:

1. **SUBDOMAIN ENUM** — run subfinder, filter (DNS + web port), fingerprint
2. **PRIORITIZE** — sort by attack value. No user approval. Just announce the order.
3. **SPAWN** — sliding window of N parallel engagements
4. Each child runs the full single-target flow autonomously
5. **CONSOLIDATED REPORT** — merge all child findings into parent report

### Progress Output

Since the user is watching but not interacting, output continuous progress:
```
Phases: [x] Recon  [x] Collect  [>] Consume & Test  [ ] Exploit  [ ] Report
[queue] 120/495 done (24%) | api: 15/21 | page: 98/464 | findings: 5
```

## Differences from /engage

| Aspect | /engage | /autoengage |
|--------|---------|-------------|
| Authentication | Asks user to choose (1-4) | Auto-skip unless auth.json exists |
| Phase transitions | Asks approval (auto-confirm default) | Never asks. Always proceeds. |
| Parallel decisions | Auto-parallel by default | Always parallel. No option to choose sequential. |
| Subdomain priority | Shows list, asks to confirm | Shows list briefly, immediately starts. |
| Error handling | May stop and ask | Logs error, continues to next task |
| Tool check | Validates Docker, shows results | Skips validation. Errors show naturally. |
| Completion | Reports and waits | Reports and sets status=completed. Done. |

## User Arguments

