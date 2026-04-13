# Command: Resume Interrupted Engagement

You are the operator resuming a previously interrupted engagement. The engagement directory and state files (scope.json, log.md, findings.md, cases.db) contain all the context needed to continue without repeating work.

## Step 1: Find Active Engagement

```bash
ROOT=/workspace
SCRIPTS="$ROOT/scripts"
source "$SCRIPTS/lib/engagement.sh"
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
printf '%s\n' "Found: $ENG_DIR"
cat "$ENG_DIR/scope.json" 2>/dev/null
if jq -e '.current_phase == "report"' "$ENG_DIR/scope.json" >/dev/null 2>&1 \
  && tail -n 80 "$ENG_DIR/log.md" 2>/dev/null | rg -F -e 'Continuous-observation handoff:' -e 'operator must enter continuous observation hold' -e 'operator must run ./scripts/finalize_engagement.sh' >/dev/null; then
    printf '%s\n' '[operator] continuous-observation handoff detected during resume; entering finalize hold'
    exec "$SCRIPTS/finalize_engagement.sh" "$ENG_DIR"
fi
```

If no engagement found or status is "completed", inform user there's nothing to resume.

If the user provided a specific engagement directory in their arguments, use that instead. After choosing the engagement, update `engagements/.active` so hooks and helper commands target the same run.

**Continuous-observation fast path:** the Step 1 shell block above is your required first resume command. It already inspects `scope.json` + the recent `log.md` tail and, if `current_phase` is `report` with a continuous-observation handoff marker (`Continuous-observation handoff:`, `operator must enter continuous observation hold`, or `operator must run ./scripts/finalize_engagement.sh`), it immediately `exec`s `"$SCRIPTS/finalize_engagement.sh" "$ENG_DIR"` inside that SAME bash/tool call. Do **not** split that detection into separate reads, `wc`, `grep`, queue stats, summary text, or an alternate command first.

If that finalize call successfully enters the observation hold, stop there. Do **not** emit a user-facing summary/final answer and do **not** perform any additional tool call unless the hold actually breaks.

## Step 2: Read Full State

```bash
# Anchor helper paths; resumed turns may start inside the engagement dir rather than /workspace.
ROOT=/workspace
SCRIPTS="$ROOT/scripts"

# Target and phase info
echo "=== Scope ==="
cat "$ENG_DIR/scope.json"

# Findings count
echo "=== Findings ==="
grep -c '^\#\# \[FINDING-' "$ENG_DIR/findings.md" 2>/dev/null || echo "0"

# Queue state
echo "=== Queue ==="
"$SCRIPTS/dispatcher.sh" "$ENG_DIR/cases.db" stats 2>/dev/null || echo "No cases.db"

# Last log entries
echo "=== Last Actions ==="
tail -30 "$ENG_DIR/log.md"

# Auth state
echo "=== Auth ==="
if [ -f "$ENG_DIR/auth.json" ]; then
    echo "Configured"
    jq '{cookies: ((.cookies // {}) | keys), headers: ((.headers // {}) | keys), tokens: ((.tokens // {}) | keys)}' "$ENG_DIR/auth.json"
else
    echo "Not configured"
fi

# Container state
echo "=== Containers ==="
source "$SCRIPTS/lib/container.sh"
export ENGAGEMENT_DIR="$ENG_DIR"
PROXY_NAME="$(_proxy_container_name)"
KATANA_NAME="$(_katana_container_name)"
docker ps --format "{{.Names}} ({{.Status}})" --filter "name=^${PROXY_NAME}$" --filter "name=^${KATANA_NAME}$" 2>/dev/null || echo "None running"
```

## Step 3: Recover Interrupted Queue State

Cases stuck in `processing` from the interrupted session are interrupted work, not proof that a live subagent is still making progress.

```bash
if [ -f "$ENG_DIR/cases.db" ]; then
    "$SCRIPTS/dispatcher.sh" "$ENG_DIR/cases.db" reset-stale 10
else
    echo "[WARN] No cases.db found — will create during Collect phase"
fi
```

For queue summaries during resume, prefer `"$SCRIPTS/dispatcher.sh" "$ENG_DIR/cases.db" stats` over ad-hoc sqlite. If you truly need custom SQL, inspect the schema first and use `url_path` rather than a nonexistent `path` column.

Do NOT assume `pwd` is `/workspace` on `/resume`. Some resumed turns start inside the engagement directory; helper calls must stay anchored to `ROOT=/workspace` / `SCRIPTS="$ROOT/scripts"` so queue recovery does not fail on relative `./scripts/...` lookups.

If `consume_test` resume is still blocked by leftover `processing` rows for the real downstream agent, log the recovery and force-reset them immediately before the next fetch:

```bash
"$SCRIPTS/append_log_entry.sh" "$ENG_DIR" operator "Resume recovery" "force-reset interrupted batch" "Recovered interrupted consume_test work on /resume after fetch was blocked by leftover processing rows"
"$SCRIPTS/dispatcher.sh" "$ENG_DIR/cases.db" reset-stale 0
```

Do not stop after this recovery step. Continue straight into the next real fetch/dispatch action in the SAME turn.

## Step 4: Restart Producers (if needed)

```bash
source "$SCRIPTS/lib/container.sh"
export ENGAGEMENT_DIR="$ENG_DIR"

# Stop any leftover crawler process/container first.
stop_katana 2>/dev/null

# Restart Katana only through the supported helper when prior crawl state exists.
if [ -f "$ENG_DIR/scans/katana_output.jsonl" ] || [ -f "$ENG_DIR/katana_output.jsonl" ]; then
    "$SCRIPTS/start_katana_ingest_background.sh" "$ENG_DIR"
fi
```

## Step 5: Resume Immediately From Real State

Do NOT present a summary and stop. Read state, recover stale work, and continue from the correct phase in the SAME turn.

Special-case report-phase resumes for long-lived observation targets: if `current_phase=report` and the recent log already shows the continuous-observation handoff markers above, that is **not** a request for more diagnostics. It is a direct instruction to run `"$SCRIPTS/finalize_engagement.sh" "$ENG_DIR"` immediately as the next action, with no intervening reads or summaries.

Determine resume point from `scope.json`, `cases.db`, and queue state:
- Queue has pending or interrupted cases → resume consumption loop (Phase 3)
- All cases done but exploit/report incomplete → proceed to the next incomplete phase
- No `cases.db` → start from collect phase (Phase 2)
- No recon data → start from recon (Phase 1)

If resuming `consume_test`, the fetch/dispatch contract is strict:
- decide the REAL downstream agent before the fetch
- NEVER fetch into `resume_operator`, `resume-operator`, or any other placeholder assignee
- `api|form|upload|graphql|websocket` → fetch for `vulnerability-analyst`
- `api-spec|page|javascript|stylesheet|data|unknown` → fetch for `source-analyzer`
- `stylesheet` MUST route to `source-analyzer` in the SAME turn; do not leave stylesheet rows parked in `processing`
- if any coverage-expanding `api-spec|javascript|unknown` rows remain pending, or a clearly seed-like root/bootstrap `page` is still unreviewed, attempt one of those `source-analyzer` fetches before taking another API-family batch
- do NOT let generic low-yield `page|stylesheet|data` backlog starve high-signal API-family testing once the coverage-expanding source backlog has already been drained
- when benchmark quality is failing/regressing or surface coverage is unresolved, prefer one coverage-expanding `source-analyzer` fetch before returning to another API-family batch so bundle-derived routes/surfaces can materialize into follow-up cases; once only generic low-yield source backlog remains, switch back to API-family testing instead of looping on more page churn
- fetch through `"$SCRIPTS/fetch_batch_to_file.sh"`; keep the full batch JSON on disk and only use the compact `BATCH_*` metadata in model context
- after the first non-empty fetch, immediately dispatch the matching subagent in the SAME turn; do not fetch a second batch first
- `./scripts/dispatcher.sh ... done` and `error` accept numeric case IDs only. Never append agent names, queue-state labels, or prose notes to those commands; log commentary separately with `append_log_entry.sh` after the queue update.
- NEVER end `/resume` on queue stats, a fetched batch, a recovery note, or a status banner like `[operator] Autoengage started and active.` without the matching `task(...)` dispatch / case-outcome update in that SAME turn
- if no advancing action is ready, write an explicit `Run stop` log entry with a stop reason instead of drifting into a status-only turn

Use this exact routing pattern when you need a queue-driven resume snippet:

```bash
ROOT=/workspace
SCRIPTS="$ROOT/scripts"
DB="$ENG_DIR/cases.db"
BATCH_FILE="$ENG_DIR/scans/resume-batch.json"
: > "$BATCH_FILE"
for spec in \
  'api-spec source-analyzer' \
  'javascript source-analyzer' \
  'unknown source-analyzer' \
  'api vulnerability-analyst' \
  'form vulnerability-analyst' \
  'upload vulnerability-analyst' \
  'graphql vulnerability-analyst' \
  'websocket vulnerability-analyst' \
  'page source-analyzer' \
  'stylesheet source-analyzer' \
  'data source-analyzer'
  do
    set -- $spec
    batch_type="$1"
    batch_agent="$2"
    : > "$BATCH_FILE"
    "$SCRIPTS/fetch_batch_to_file.sh" "$DB" "$batch_type" 10 "$batch_agent" "$BATCH_FILE"
    if [ -s "$BATCH_FILE" ]; then
      printf 'FETCH_TYPE=%s\nFETCH_AGENT=%s\nFETCH_PATH=%s\n' "$batch_type" "$batch_agent" "$BATCH_FILE"
      break
    fi
  done
```

In AUTO-CONFIRM mode: announce and proceed immediately.
In MANUAL mode: present numbered choice only when a real phase choice is still needed.

## User Arguments

Optional: specific engagement directory path. If empty, uses most recent.
