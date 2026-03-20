---
name: case-dispatching
description: Guide operator through the case queue consumption loop for security testing
origin: RedteamOpencode
---

# Case Dispatching Skill

This skill guides the operator through consuming the case queue — fetching batches of cases from `cases.db`, routing them to the appropriate subagent, and tracking completion.

## When to Activate

- After `/engage` initialization when `cases.db` is created
- When cases exist in the queue with status `pending`
- When a producer (proxy, katana, recon ingest, spec ingest) has added new cases

## The Consumption Loop

The operator drives a continuous loop until all cases are processed.

**CRITICAL ROUTING RULE: You MUST fetch cases by type separately and route each type
to the CORRECT agent per the routing table below. NEVER fetch all types at once.
NEVER send page/javascript/stylesheet/data cases to vulnerability-analyst.
NEVER send api/form/upload cases to source-analyzer.**

Each iteration of the loop:

```
1. Reset stale: ./scripts/dispatcher.sh $DB reset-stale 10
2. Check stats: ./scripts/dispatcher.sh $DB stats
3. For EACH consumable type with pending > 0, fetch and route SEPARATELY:

   --- vulnerability-analyst types ---
   ./scripts/dispatcher.sh $DB fetch api 10 vulnerability-analyst
   ./scripts/dispatcher.sh $DB fetch form 10 vulnerability-analyst
   ./scripts/dispatcher.sh $DB fetch upload 10 vulnerability-analyst
   ./scripts/dispatcher.sh $DB fetch graphql 10 vulnerability-analyst
   ./scripts/dispatcher.sh $DB fetch websocket 10 vulnerability-analyst

   --- source-analyzer types ---
   ./scripts/dispatcher.sh $DB fetch page 10 source-analyzer
   ./scripts/dispatcher.sh $DB fetch javascript 10 source-analyzer
   ./scripts/dispatcher.sh $DB fetch stylesheet 10 source-analyzer
   ./scripts/dispatcher.sh $DB fetch data 10 source-analyzer

4. For each fetched batch:
   a. Dispatch to the agent specified in the fetch command
   b. When subagent returns:
      - Mark completed: ./scripts/dispatcher.sh $DB done "id1,id2,..."
      - If new endpoints found: echo JSON | ./scripts/dispatcher.sh $DB requeue
      - If findings: record to findings.md
   c. If subagent fails: ./scripts/dispatcher.sh $DB error "id1,id2,..."
5. If pending = 0 and all producers stopped → report completion
6. Otherwise → loop back to step 1
```

**You can dispatch vulnerability-analyst and source-analyzer batches IN PARALLEL
(they handle different case types, no conflict).**

## Type to Agent Routing Table

| Type | Agent | Notes |
|------|-------|-------|
| api | vulnerability-analyst | REST endpoint testing |
| form | vulnerability-analyst | Form submission testing |
| upload | vulnerability-analyst | File upload testing |
| graphql | vulnerability-analyst | GraphQL query testing |
| websocket | vulnerability-analyst | WebSocket testing |
| page | source-analyzer | HTML page analysis |
| javascript | source-analyzer | JS static analysis |
| stylesheet | source-analyzer | CSS analysis for data leaks |
| data | source-analyzer | JSON/XML data analysis |
| unknown | operator | Operator reviews manually and reclassifies |
| image | skipped | Future agents |
| video | skipped | Future agents |
| font | skipped | Future agents |
| archive | skipped | Future agents |

## Batch Strategy

- Fetch up to 10 same-type cases per cycle
- Do not wait for accumulation — dispatch whatever is pending immediately
- Natural pacing comes from subagent execution time
- Process higher-value types first: api > form > graphql > page > javascript > others

## Key Rules

- **ALWAYS** use `./scripts/dispatcher.sh` for all queue operations (zero token cost for queue management)
- **NEVER** read `cases.db` directly with `sqlite3` — always use the dispatcher interface
- Record every finding to `findings.md` immediately after a subagent reports it
- Requeue new endpoints discovered by agents — the dispatcher handles deduplication automatically
- When a subagent errors on a batch, mark those cases with `error` so they can be retried later
- Use `reset-stale <minutes>` at the start of each loop iteration to reclaim abandoned cases

**CRITICAL — DO NOT STOP THE LOOP EARLY:**
- The loop MUST continue running until `pending = 0` for ALL consumable types.
- After completing one batch, IMMEDIATELY fetch the next batch. Do NOT present a
  "resume complete" message and wait. Do NOT summarize and stop.
- If a subagent call fails with an error (e.g., ProviderModelNotFoundError), mark
  those cases as `error`, log the issue, and CONTINUE with the next batch.
  Do NOT stop the entire loop because one batch failed.
- The only valid reasons to stop: pending=0 everywhere, or user types /stop.
- With 17,000+ pending cases, expect hundreds of loop iterations. This is normal.

## Dispatcher Quick Reference

```bash
DB="<engagement_dir>/cases.db"

# View queue statistics
./scripts/dispatcher.sh "$DB" stats

# Fetch a batch of cases (marks them processing)
./scripts/dispatcher.sh "$DB" fetch <type> <limit> <agent_name>

# Mark cases as completed
./scripts/dispatcher.sh "$DB" done "id1,id2,id3"

# Mark cases as errored
./scripts/dispatcher.sh "$DB" error "id1,id2,id3"

# Reset cases stuck processing for more than N minutes
./scripts/dispatcher.sh "$DB" reset-stale <minutes>

# Requeue new endpoints (pipe JSON lines via stdin, one object per line)
echo '{"url":"...","method":"GET","type":"api"}' | ./scripts/dispatcher.sh "$DB" requeue
```
