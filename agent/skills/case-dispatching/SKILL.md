---
name: case-dispatching
description: Guide operator through the case queue consumption loop for security testing
origin: RedteamOpencode
---

# Case Dispatching

Guides consumption of the case queue — fetching batches from `cases.db`, routing to subagents, tracking completion.

## When to Activate

- After `/engage` when `cases.db` is created
- When pending cases exist in queue
- When a producer has added new cases

## The Consumption Loop

**CRITICAL: Fetch cases by type SEPARATELY. Route per table below. NEVER mix types.
NEVER send page/js/css/data to vulnerability-analyst. NEVER send api/form/upload to source-analyzer.**

Each iteration:
```
1. Reset stale: ./scripts/dispatcher.sh $DB reset-stale 10
2. Check stats: ./scripts/dispatcher.sh $DB stats
3. Fetch and route by type (SERIALIZED: exactly one non-empty batch per loop pass):

   vulnerability-analyst: api, api-spec, form, upload, graphql, websocket
   source-analyzer: page, javascript, stylesheet, data, unknown

   ./scripts/dispatcher.sh $DB fetch <type> 10 <agent_name>
   - choose the REAL downstream assignee before fetching; never park a batch under `resume_operator`, `resume-operator`, or any other placeholder assignee
   - every non-empty fetch MUST be followed by exactly one matching subagent dispatch in the SAME turn
   - never fetch a second batch until the first batch's `### Case Outcomes` have been recorded with `done` / `requeue` / `error`
   - never leave fetched rows in `processing` without a corresponding live subagent task

4. On subagent return:
   - Done: ./scripts/dispatcher.sh $DB done "id1,id2,..."
   - New endpoints: echo JSON | ./scripts/dispatcher.sh $DB requeue
   - Findings: record to findings.md
   - Errors: ./scripts/dispatcher.sh $DB error "id1,id2,..."
5. pending=0 and producers stopped → report completion
6. Otherwise → loop back to step 1
```

## Type → Agent Routing

| Type | Agent | Type | Agent |
|------|-------|------|-------|
| api | vulnerability-analyst | page | source-analyzer |
| api-spec | vulnerability-analyst | page | source-analyzer |
| form | vulnerability-analyst | javascript | source-analyzer |
| upload | vulnerability-analyst | stylesheet | source-analyzer |
| graphql | vulnerability-analyst | data | source-analyzer |
| websocket | vulnerability-analyst | unknown | source-analyzer |
| image/video/font/archive | skipped | | |

## Batch Strategy

- Up to 10 same-type cases per cycle, dispatch immediately
- Priority: api-spec > api > form > graphql > page > javascript > others

## Progress Display (after EVERY batch)

```
Phases: [x] Recon  [x] Collect  [>] Consume & Test  [ ] Exploit  [ ] Report
[queue] 120/495 done (24%) | api: 15/21 | page: 98/464 | js: 7/10 | findings: 5
```
```bash
sqlite3 "$DB" ".timeout 5000" "
  SELECT type, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
    SUM(CASE WHEN status!='skipped' THEN 1 ELSE 0 END) as total
  FROM cases GROUP BY type ORDER BY total DESC;"
```

## Key Rules

- ALWAYS use `./scripts/dispatcher.sh` for queue ops (never read cases.db directly)
- Record findings to findings.md immediately
- Requeue new endpoints (dispatcher handles dedup)
- Use reset-stale at start of each iteration
- **DO NOT STOP EARLY** — loop until pending=0 for all consumable types
- On subagent error: mark cases `error`, log, CONTINUE (don't halt loop)
- Only stop on: pending=0 everywhere, or user /stop

## Dispatcher Quick Reference

```bash
DB="<engagement_dir>/cases.db"
./scripts/dispatcher.sh "$DB" stats
./scripts/dispatcher.sh "$DB" fetch <type> <limit> <agent_name>
./scripts/dispatcher.sh "$DB" done "id1,id2,id3"
./scripts/dispatcher.sh "$DB" error "id1,id2,id3"
./scripts/dispatcher.sh "$DB" reset-stale <minutes>
echo '{"url":"...","method":"GET","type":"api"}' | ./scripts/dispatcher.sh "$DB" requeue
```
