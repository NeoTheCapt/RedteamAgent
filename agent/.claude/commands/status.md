# Command: Engagement Status

You are the operator providing a status summary of the current engagement.

## Step 1: Load Engagement State

Locate the most recent engagement directory under `engagements/`. Read:
- `scope.json` -- target, scope, mode, status, phases completed, current phase
- `findings.md` -- count findings by severity

Also read queue stats if cases.db exists:
```bash
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
PHASES=$(jq -r '.phases_completed // [] | join(", ")' "$ENG_DIR/scope.json" 2>/dev/null)
CURRENT=$(jq -r '.current_phase // "unknown"' "$ENG_DIR/scope.json" 2>/dev/null)
FINDINGS=$(grep -c '^\#\# \[FINDING-' "$ENG_DIR/findings.md" 2>/dev/null || echo 0)
./scripts/dispatcher.sh "$ENG_DIR/cases.db" stats 2>/dev/null
```

## Step 2: Display Status Dashboard

```
╔══════════════════════════════════════════════════════════╗
║  ENGAGEMENT STATUS                                       ║
╠══════════════════════════════════════════════════════════╣
║  Target:  <target URL>                                   ║
║  Phase:   <current_phase>                                ║
║  Mode:    <auto-confirm | manual>                        ║
╠══════════════════════════════════════════════════════════╣
║  PHASES                                                  ║
║  [x] Recon           ← completed / [ ] pending           ║
║  [x] Collect         ← completed / [ ] pending           ║
║  [>] Consume & Test  ← IN PROGRESS / [ ] pending         ║
║  [ ] Exploit         ← pending                           ║
║  [ ] Report          ← pending                           ║
╠══════════════════════════════════════════════════════════╣
║  CASE QUEUE                                              ║
║  Total:      <N>                                         ║
║  Pending:    <N>  ████████░░░░░░░░  XX%                  ║
║  Done:       <N>  ████████████░░░░  XX%                  ║
║  Processing: <N>                                         ║
║  Error:      <N>                                         ║
║  Skipped:    <N>                                         ║
╠══════════════════════════════════════════════════════════╣
║  QUEUE BY TYPE                                           ║
║  api:        <done>/<total>  ████████░░  XX%             ║
║  page:       <done>/<total>  ██████░░░░  XX%             ║
║  javascript: <done>/<total>  ██████████  100%            ║
║  form:       <done>/<total>  ░░░░░░░░░░  0%             ║
╠══════════════════════════════════════════════════════════╣
║  FINDINGS: <total>                                       ║
║  HIGH: <N>  MEDIUM: <N>  LOW: <N>  INFO: <N>            ║
╠══════════════════════════════════════════════════════════╣
║  CONTAINERS                                              ║
║  katana:  running / stopped                              ║
║  proxy:   running / stopped                              ║
╚══════════════════════════════════════════════════════════╝
```

For the progress bars, use Unicode block characters:
- `█` for completed portion
- `░` for remaining portion
- Calculate percentage: `done * 100 / total`
- Bar width: 10 characters

To get per-type stats:
```bash
sqlite3 "$ENG_DIR/cases.db" ".timeout 5000" "
  SELECT type,
    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
    COUNT(*) as total
  FROM cases
  WHERE status != 'skipped'
  GROUP BY type
  ORDER BY total DESC;"
```

## Step 3: Container Status

```bash
docker ps --format "{{.Names}} ({{.Status}})" --filter "name=redteam" 2>/dev/null
```

## User Arguments

Additional context from the user follows:
