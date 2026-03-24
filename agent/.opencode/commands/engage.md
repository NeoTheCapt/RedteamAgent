# Command: Engage Target

You are the operator initiating a new red team engagement. The user has provided a target URL/IP as arguments below this template. Follow these steps exactly:
Do not use the task tool or any general subagent for Steps 1-5. Perform initialization directly as the operator.

**Interaction mode detection from arguments:**
- `--auto` flag present → **AUTONOMOUS MODE**: zero interaction, never ask user, never stop. If something fails, log and move on.
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

**IMPORTANT: Use bash commands to create all engagement files. Do NOT use the Write tool — it will fail on new files.**
**IMPORTANT: Before Step 2 completes, do NOT read `scope.json`, `log.md`, `findings.md`, `intel.md`, `auth.json`, or `cases.db` — they do not exist yet.**
**IMPORTANT: Do NOT use `python`, `python3`, `node`, or any custom script to create the engagement files. Use the bash block below directly.**

Determine the directory name:
- Format: `engagements/<YYYY-MM-DD>-<HHMMSS>-<hostname>/`
- Use today's date in `YYYY-MM-DD` format and current time in `HHMMSS` format.
- Sanitize the hostname (replace dots with dashes, remove special characters).
- The timestamp ensures uniqueness — no collision even for multiple engagements against the same target on the same day.

Use a single bash command block to create everything.
Do not rewrite it into another language or split it into multiple tool calls.
Do not chain heredoc writes with `&&` on the `EOF` line or immediately after it. That causes `zsh` parse errors.
Prefer `set -e` and plain newline-separated commands inside one block.

**CRITICAL: Do NOT use single-quoted heredoc delimiters (like `<< 'SCOPE'`) for content that
contains shell variables or command substitutions. Use unquoted delimiters (like `<< SCOPE`)
so that `$VARIABLE` and `$(command)` are properly expanded.**

Compute all values FIRST as shell variables, then write files using those variables:

```bash
set -e

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
printf '%s\n' "$DIR" > engagements/.active

# NOTE: Use unquoted heredoc (no quotes around EOF) so variables expand
cat > "$DIR/scope.json" << EOF
{
  "target": "${TARGET}",
  "hostname": "${HOSTNAME_RAW}",
  "port": ${PORT},
  "scope": ["${HOSTNAME_RAW}", "*.${HOSTNAME_RAW}"],
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

: > "$DIR/surfaces.jsonl"
printf '[]\n' > "$DIR/intel-secrets.json"

echo "{}" > "$DIR/auth.json"

sqlite3 "$DIR/cases.db" < scripts/schema.sql

cp scripts/templates/intel.md "$DIR/intel.md" 2>/dev/null || echo "# Intelligence Collection" > "$DIR/intel.md"
awk '
  /^[[:space:]]*#/ { next }
  /^[[:space:]]*$/ { next }
  { lines[++count] = $0 }
  END {
    srand()
    if (count > 0) {
      print lines[int(rand() * count) + 1]
    }
  }
' scripts/templates/user-agents.txt > "$DIR/user-agent.txt"
cp scripts/templates/rtcurl.sh "$DIR/tools/rtcurl"
chmod +x "$DIR/tools/rtcurl"

echo "$DIR"
```

Replace all `<placeholder>` comments above with actual parsed values from Step 1.
The key point: `$DATE`, `$START_TIME` etc. MUST be shell variables that expand at write time.
Keep each heredoc as a standalone command:
`cat << EOF ... EOF`
Then start the next command on a new line. Do not write `EOF && next_command`.
When writing Markdown via unquoted heredoc, do not include raw backticks like `` `cmd` `` inside the body.
Either escape them as `\`cmd\`` or write plain text, otherwise shell command substitution may run unexpectedly.

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

## Step 4: Configure Authentication

**AUTONOMOUS MODE**: skip auth setup. If `auth.json` already has `cookies` or `headers`, use them. Proxy-detected bearer-style login tokens are promoted into `auth.json.headers.Authorization` automatically when possible. Otherwise start unauthenticated — operator Credential Auto-Use rules apply during engagement. Never wait for approval prompts.

**INTERACTIVE MODE**: Present to user:
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

## Step 5: Start Producers

Start the pipeline regardless of auth choice (skip or configured):

1. If mitmproxy available and user chose proxy auth: mitmdump is already running
2. Start Katana crawler (if installed): `./scripts/katana_ingest.sh "$DIR" > "$DIR/scans/katana_ingest.log" 2>&1 < /dev/null &`
   (Katana crawls without auth if skipped — still discovers unauthenticated endpoints)
3. ALL subsequent phases (Recon → Collect → Consume & Test → Exploit → Report) proceed normally

## Step 6: Begin Engagement Loop

The engagement loop starts only after Steps 1-5 finish successfully. Do not enter the operator core loop early.

Before Phase 1 begins, initialize OpenCode's native progress UI with `todowrite` following
the operator progress rules in `prompts/agents/operator.txt`. At each later phase transition,
update the same todo list there. Do not rely on `/status` alone for progress UI; the right-side
TUI progress panel is driven by the todo list.

### Phase 1: RECON

1. Log the engagement start in `log.md` via:
   `./scripts/append_log_entry.sh "$DIR" operator "Engagement start" "phase 1 recon" "initialized workspace and starting recon"`
2. Present recon plan — MUST dispatch BOTH agents in parallel:
   - **recon-specialist**: HTTP fingerprinting, directory fuzzing, port scanning
   - **source-analyzer**: HTML/JS/CSS analysis for hidden routes, API endpoints, secrets
3. **INTERACTIVE MODE**: wait for user approval before sending traffic.
   **AUTONOMOUS MODE**: announce recon start, then send traffic immediately.
4. After recon completes, record ALL findings to `findings.md`.
5. At every later phase transition, append one concise operator timeline entry via `./scripts/append_log_entry.sh`.

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
1. Import only concrete queue-ready endpoints:
   - recon-specialist: use `#### Queue Endpoints` JSONL only
   - source-analyzer: use fully concrete, directly requestable JSONL endpoints only
   `echo "endpoint-jsonl" | ./scripts/recon_ingest.sh "$DIR/cases.db" <source>`
   Dynamic templates, string fragments, route constants, unresolved placeholders, and write endpoints
   without real parameters belong in `Surface Candidates`, not `cases.db`.
2. Start Katana container + ingest pipeline:
   ```bash
   source scripts/lib/container.sh
   export ENGAGEMENT_DIR="$DIR"
   start_katana "TARGET_URL"
   # Start ingest in background — monitors katana output and feeds cases.db
   ./scripts/katana_ingest.sh "$DIR" > "$DIR/scans/katana_ingest.log" 2>&1 < /dev/null &
   echo "[katana] Crawler + ingest running in background"
   ```
3. Show queue stats: `./scripts/dispatcher.sh "$DIR/cases.db" stats`

### Phase 3: CONSUME & TEST (main testing loop)

Follow the case-dispatching skill methodology. For each cycle:
1. `./scripts/dispatcher.sh "$DIR/cases.db" reset-stale 10`
2. `./scripts/dispatcher.sh "$DIR/cases.db" stats`
3. Fetch batch by type → dispatch to appropriate agent → mark done → requeue new endpoints
4. Continue until queue empty + producers stopped

Before leaving Test phase, run:
`./scripts/check_surface_coverage.sh "$DIR"`

If it fails, do not advance yet. Resolve each remaining discovered surface by marking it
`covered`, `deferred`, or `not_applicable`.

### Phase 4: EXPLOIT

Dispatch osint-analyst + exploit-developer in parallel.
After osint-analyst: read intel.md, high-value → findings.md + exploit-developer 2nd round.

### Phase 5: REPORT

Dispatch report-writer with engagement directory.

**INTERACTIVE**: Request user approval at each phase transition.
**AUTONOMOUS**: Never ask approval, always parallel, errors → log and continue.

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

Process max N subdomains in parallel (default 3). Each runs full 5-phase flow with engagement-scoped proxy/Katana containers.
When one completes → start next. NEVER create all directories upfront.

WAF gate check before each: skip if 403 + Cloudflare/CloudFront challenge.

### Phase FINAL: Consolidated Report

Merge all child findings.md into parent report.md.

---

## User Arguments

The target and any additional context from the user follows:
