# Command: Resume Interrupted Engagement

You are the operator resuming a previously interrupted engagement. The engagement directory and state files (scope.json, log.md, findings.md, cases.db) contain all the context needed to continue without repeating work.

## Step 1: Find Active Engagement

```bash
source scripts/lib/engagement.sh
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
echo "Found: $ENG_DIR"
cat "$ENG_DIR/scope.json" 2>/dev/null
```

If no engagement found or status is "completed", inform user there's nothing to resume.

If the user provided a specific engagement directory in their arguments, use that instead. After choosing the engagement, update `engagements/.active` so hooks and helper commands target the same run.

## Step 2: Read Full State

```bash
# Target and phase info
echo "=== Scope ==="
cat "$ENG_DIR/scope.json"

# Findings count
echo "=== Findings ==="
grep -c '^\#\# \[FINDING-' "$ENG_DIR/findings.md" 2>/dev/null || echo "0"

# Queue state
echo "=== Queue ==="
./scripts/dispatcher.sh "$ENG_DIR/cases.db" stats 2>/dev/null || echo "No cases.db"

# Last log entries
echo "=== Last Actions ==="
tail -30 "$ENG_DIR/log.md"

# Auth state
echo "=== Auth ==="
if [ -f "$ENG_DIR/auth.json" ]; then
    echo "Configured"
    jq '{cookies: ((.cookies // {}) | keys), headers: ((.headers // {}) | keys)}' "$ENG_DIR/auth.json"
else
    echo "Not configured"
fi

# Container state
echo "=== Containers ==="
docker ps --format "{{.Names}} ({{.Status}})" --filter "name=redteam" 2>/dev/null || echo "None running"
```

## Step 3: Reset Stale Cases

Cases stuck in "processing" from the interrupted session need to be returned to the queue:

```bash
if [ -f "$ENG_DIR/cases.db" ]; then
    ./scripts/dispatcher.sh "$ENG_DIR/cases.db" reset-stale 10
else
    echo "[WARN] No cases.db found — will create during Collect phase"
fi
```

## Step 4: Restart Producers (if needed)

```bash
source scripts/lib/container.sh
export ENGAGEMENT_DIR="$ENG_DIR"
TARGET=$(jq -r '.target' "$ENG_DIR/scope.json")

# Stop any leftover containers first
stop_katana 2>/dev/null

# Restart Katana if there's a previous output file (was running before)
if [ -f "$ENG_DIR/scans/katana_output.jsonl" ]; then
    start_katana "$TARGET"
    # Also restart the ingest pipeline
    ./scripts/katana_ingest.sh "$ENG_DIR" > "$ENG_DIR/scans/katana_ingest.log" 2>&1 &
fi
```

## Step 5: Present Summary and Resume

Present a brief summary to the user, then resume from where we left off.

Determine resume point from scope.json `phases_completed` and queue state:
- Queue has pending cases → resume consumption loop (Phase 3)
- All cases done but no exploit phase → proceed to exploit (Phase 4)
- Everything done → proceed to report (Phase 5)
- No cases.db → start from collect phase (Phase 2)
- No recon data → start from recon (Phase 1)

In AUTO-CONFIRM mode: announce and proceed immediately.
In MANUAL mode: present numbered choice for which phase to resume from.

## User Arguments

Optional: specific engagement directory path. If empty, uses most recent.
