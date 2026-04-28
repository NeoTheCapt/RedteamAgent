
## Structured event stream

See `agent/scripts/EVENTS.md` for the event protocol. The backend
accepts structured events via `POST /projects/:p/runs/:r/events` with
optional `kind`/`level`/`payload` fields, persists them to the extended
`events` table, and calls `app/services/event_apply.py` to upsert
secondary `dispatches`/`cases` rows for known `kind` values. Every event
is forwarded to WS clients via `broadcaster.publish`.

Read endpoints:
- `GET /projects/:p/runs/:r/summary` — aggregates (dispatches + cases counts)
- `GET /projects/:p/runs/:r/dispatches` — filterable dispatch list
- `GET /projects/:p/runs/:r/cases` / `.../cases/:case_id` — cases + detail
- `GET /projects/:p/runs/:r/documents` / `.../documents/:path` — run artifacts
