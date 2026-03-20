# Command: Engage Target

You are the operator initiating a new red team engagement. The user has provided a target URL/IP as arguments below this template. Follow these steps exactly:

## Step 1: Parse Target

Extract the target URL from the user's arguments appended after this template. Identify:
- Full URL (scheme, host, port, path)
- Hostname (for directory naming and scope derivation)
- Port (default 80/443 if not specified)

If no target is provided in the arguments, ask the user for one before proceeding.

## Step 2: Create Engagement Directory and Files

**IMPORTANT: Use bash commands to create all engagement files. Do NOT use the Write tool — it will fail on new files.**

Determine the directory name:
- Format: `engagements/<YYYY-MM-DD>-<HHMMSS>-<hostname>/`
- Use today's date in `YYYY-MM-DD` format and current time in `HHMMSS` format.
- Sanitize the hostname (replace dots with dashes, remove special characters).
- The timestamp ensures uniqueness — no collision even for multiple engagements against the same target on the same day.

Use a single bash command block to create everything.

**CRITICAL: Do NOT use single-quoted heredoc delimiters (like `<< 'SCOPE'`) for content that
contains shell variables or command substitutions. Use unquoted delimiters (like `<< SCOPE`)
so that `$VARIABLE` and `$(command)` are properly expanded.**

Compute all values FIRST as shell variables, then write files using those variables:

```bash
# Compute values first
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M%S)
HOSTNAME_CLEAN="<hostname with dots replaced by dashes>"
TARGET="<full target URL>"
HOSTNAME_RAW="<original hostname>"
PORT=<port number>
START_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

DIR="engagements/${DATE}-${TIME}-${HOSTNAME_CLEAN}"
mkdir -p "$DIR/tools" "$DIR/downloads" "$DIR/scans" "$DIR/pids"

# NOTE: Use unquoted heredoc (no quotes around EOF) so variables expand
cat > "$DIR/scope.json" << EOF
{
  "target": "${TARGET}",
  "hostname": "${HOSTNAME_RAW}",
  "port": ${PORT},
  "scope": ["${HOSTNAME_RAW}", "*.${HOSTNAME_RAW}"],
  "mode": "ctf",
  "status": "in_progress",
  "start_time": "${START_TIME}",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF

cat > "$DIR/log.md" << EOF
# Engagement Log

- **Target**: ${TARGET}
- **Date**: ${DATE}
- **Mode**: CTF
- **Status**: In Progress

---
EOF

cat > "$DIR/findings.md" << EOF
# Findings

- **Target**: ${TARGET}
- **Engagement Date**: ${DATE}
- **Finding Count**: 0

---
EOF
```

Replace all `<placeholder>` comments above with actual parsed values from Step 1.
The key point: `$DATE`, `$START_TIME` etc. MUST be shell variables that expand at write time.

## Step 3: Environment Check (Docker)

All pentest tools run in Docker containers. Check prerequisites:

```bash
source scripts/lib/container.sh

echo ""
echo "=== Docker Check ==="
check_docker

echo ""
echo "=== Image Check ==="
check_images

echo ""
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
Wait for user to confirm images are built before proceeding.

If Docker is not installed, the engagement CANNOT proceed. Tell the user to install Docker first.

## Step 4: Initialize Case Queue

Initialize the SQLite case queue database:

```bash
sqlite3 "$DIR/cases.db" < scripts/schema.sql
```

## Step 5: Configure Authentication

Present to user:
```
Authentication setup:
  1 — Proxy login (recommended: captures real session)
  2 — Paste cookie manually
  3 — Paste auth header manually
  4 — Skip (test unauthenticated only)

Reply (1-4):
```

Wait for user response. Handle:
- `1` → tell user to run `/proxy start` then login in browser
- `2` → ask user to paste cookie string, then run `/auth cookie "<value>"`
- `3` → ask user to paste header, then run `/auth header "<value>"`
- `4` → skip auth, proceed immediately

**If user chooses 4 (skip):** Authentication is skipped but ALL subsequent steps still
execute normally. Katana crawls without cookies, vulnerability tests run without auth
headers. Collect and Consume phases still happen — they just test unauthenticated attack
surface. The user can configure auth later at any time with `/auth`.

## Step 6: Start Producers

Start the pipeline regardless of auth choice (skip or configured):

1. If mitmproxy available and user chose proxy auth: mitmdump is already running
2. Start Katana crawler (if installed): `./scripts/katana_ingest.sh "$DIR" &`
   (Katana crawls without auth if skipped — still discovers unauthenticated endpoints)
3. ALL subsequent phases (Recon → Collect → Consume & Test → Exploit → Report) proceed normally

## Step 7: Begin Autonomous Engagement Loop

### Phase 1: RECON

1. Log the engagement start in `log.md`.
2. Present recon plan — MUST dispatch BOTH agents in parallel:
   - **recon-specialist**: HTTP fingerprinting, directory fuzzing, port scanning
   - **source-analyzer**: HTML/JS/CSS analysis for hidden routes, API endpoints, secrets
3. Wait for user approval before sending traffic.
4. After recon completes, record ALL findings to `findings.md`.

### Phase 2: COLLECT (start immediately after recon)

This is NOT optional.

**In auto-confirm mode (default):** Announce and proceed immediately:
```
[operator] Recon complete. Starting collection:
  - Importing N endpoints into case queue
  - Starting Katana crawler
  - Queue: [show dispatcher.sh stats]
```

**In manual mode:** Present numbered choice:
```
  1 — Start collection + consumption
  2 — Skip to exploit phase
Reply (1-2):
```

After approval:
1. Import recon/source-analyzer endpoints: `echo "endpoints" | ./scripts/recon_ingest.sh "$DIR/cases.db" recon-specialist`
2. Start Katana container + ingest pipeline:
   ```bash
   source scripts/lib/container.sh
   export ENGAGEMENT_DIR="$DIR"
   start_katana "TARGET_URL"
   # Start ingest in background — monitors katana output and feeds cases.db
   ./scripts/katana_ingest.sh "$DIR" > "$DIR/scans/katana_ingest.log" 2>&1 &
   echo "[katana] Crawler + ingest running in background"
   ```
3. Show queue stats: `./scripts/dispatcher.sh "$DIR/cases.db" stats`

### Phase 3: CONSUME & TEST (main testing loop)

Follow the case-dispatching skill methodology. For each cycle:
1. `./scripts/dispatcher.sh "$DIR/cases.db" reset-stale 10`
2. `./scripts/dispatcher.sh "$DIR/cases.db" stats`
3. Fetch batch by type → dispatch to appropriate agent → mark done → requeue new endpoints
4. Continue until queue empty + producers stopped

### Phase 4: EXPLOIT

For confirmed findings, dispatch exploit-developer (parallel for independent findings).

### Phase 5: REPORT

Dispatch report-writer with engagement directory.

Request user approval at each phase transition.

## User Arguments

The target and any additional context from the user follows:
