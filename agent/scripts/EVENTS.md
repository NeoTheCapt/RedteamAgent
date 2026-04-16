# Agent Event Protocol

Agent scripts emit runtime events by POSTing to the orchestrator
`POST /projects/:project_id/runs/:run_id/events` endpoint via
`agent/scripts/emit_runtime_event.sh`. The orchestrator persists every event
into the `events` table, upserts secondary `dispatches`/`cases` rows based on
`kind`, and broadcasts the event to any connected WebSocket clients.

## Invocation

```
emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>
                      [--kind <kind>]
                      [--level <info|warn|error|ok|debug|find>]
                      [--payload-json <json>]
```

- First 5 positional args are the **legacy contract** used by `append_finding.sh`,
  `append_surface.sh`, and `append_log_entry.sh`. These callers post events
  with `kind=legacy` (the backend treats them as insert-only, no side effects).
- The three optional flags produce **structured events** that the orchestrator
  event_apply service routes into typed side effects.

## Required environment

If any of these are unset, the script no-ops silently (safe in local dev):

- `ORCHESTRATOR_BASE_URL`
- `ORCHESTRATOR_TOKEN`
- `ORCHESTRATOR_PROJECT_ID`
- `ORCHESTRATOR_RUN_ID`

## Structured kinds

The orchestrator's `app/services/event_apply.py` recognizes these `kind` values
and mutates secondary tables on top of the base event row. Any unknown kind
(and any legacy event without `--kind`) is persisted as-is with no side effect.

| kind             | required payload                                     | effect                                                                     |
|------------------|------------------------------------------------------|----------------------------------------------------------------------------|
| `phase_enter`    | `{"phase": str}`                                     | `UPDATE runs SET current_phase = payload.phase WHERE id = run_id`          |
| `dispatch_start` | `{"batch": str, "round": int, "slot": str, "agent": str, "case_count": int, "type"?, "task"?, "cases"?}` | upsert `dispatches` row (state=running); if `cases[]` present, pre-seed `cases` rows with method/path (state=queued) |
| `dispatch_done`  | `{"batch": str, "state": "done" \| "missing_outcomes" \| "failed"}` | update `dispatches` (state, finished_at)                                   |
| `case_done`      | `{"case_id": int, "outcome": "DONE" \| "REQUEUE" \| "ERROR", "dispatch"?: str, "agent"?, "type"?, "detail"?}` | upsert `cases` row; state derived from outcome (DONE→done, REQUEUE→queued, ERROR→error) |
| `finding`        | `{"finding_id": str, "severity": str, "category": str, "title": str, "case_id"?: int, "method"?, "path"?}` | if `case_id` present, update case row state=finding with finding_id. Otherwise event-only. |
| `legacy` (default) | any shape                                          | insert-only; no side effect on dispatches/cases/runs                       |

## Event shape on the wire

Example structured `dispatch_start` POST body:

```json
{
  "event_type": "dispatch.started",
  "phase": "consume",
  "task_name": "B-17",
  "agent_name": "vulnerability-analyst:s0",
  "summary": "api batch B-17 (3 cases)",
  "kind": "dispatch_start",
  "level": "info",
  "payload": {
    "batch": "B-17",
    "round": 2,
    "slot": "0",
    "case_count": 3,
    "type": "api",
    "agent": "vulnerability-analyst",
    "cases": [
      {"id": 31, "method": "GET", "path": "/api/products", "type": "api"},
      {"id": 32, "method": "GET", "path": "/api/search",   "type": "api"},
      {"id": 33, "method": "POST","path": "/rest/reviews", "type": "api"}
    ]
  }
}
```

## Emission sites (agent → orchestrator)

- `parallel_dispatch.sh fetch` → `dispatch_start` per per-slot manifest.
  Includes the `cases[]` array harvested from `fetch_batch_to_file.sh` output.
- `parallel_dispatch.sh record` → `case_done` per parsed outcome,
  `dispatch_done` per batch (plus an additional orphan-recovery `dispatch_done`
  with `state: "missing_outcomes"` when outcomes files are absent).
- `append_finding.sh` → `finding` with `finding_id`/`severity`/`category`/`title`.
- `finalize_engagement.sh` → `phase_enter` at `report` and `complete` transitions.

## WebSocket broadcast

Every successful `POST /events` is republished via `broadcaster.publish`
to any WS client connected to `/ws/projects/:p/runs/:r?ticket=...`. The
broadcast envelope carries the full event payload including `kind`/`level`
so frontend clients can filter and render without re-fetching.

## Read endpoints

After events land, the structured data is available via:

- `GET /projects/:p/runs/:r/summary` — run-level aggregates, including
  `dispatches.{total,active,done,failed}` and `cases.{total,done,running,queued,error,findings}`.
- `GET /projects/:p/runs/:r/dispatches?phase=consume` — list of dispatch records.
- `GET /projects/:p/runs/:r/cases?state=finding&method=GET&category=injection` — filterable case list.
- `GET /projects/:p/runs/:r/cases/:case_id` — single case detail with `duration_ms`.
- `GET /projects/:p/runs/:r/documents` — folder-scoped file tree (findings/intel/surface/artifacts/reports).
- `GET /projects/:p/runs/:r/documents/{path:path}` — file content (text, ≤1 MB).

See `docs/superpowers/specs/2026-04-17-orchestrator-refactor-design.md` for the
full architectural context.
