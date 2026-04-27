from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.runs import _project_or_404

router = APIRouter(
    prefix="/projects/{project_id}/runs/{run_id}/dispatches",
    tags=["dispatches"],
)

# Agent identifiers and the launcher/operator/dispatcher infrastructure roles
# we exclude when reconstructing dispatches from events.
_INFRA_AGENTS = {"launcher", "operator", "dispatcher", "", None}


def _serialize(d) -> dict:
    return {
        "id": d.id,
        "phase": d.phase,
        "round": d.round,
        "agent": d.agent,
        "slot": d.slot,
        "task": d.task,
        "state": d.state,
        "started_at": d.started_at,
        "finished_at": d.finished_at,
        "error": d.error,
    }


def _iso_to_epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        # SQLite default CURRENT_TIMESTAMP stores 'YYYY-MM-DD HH:MM:SS' in UTC.
        dt = datetime.fromisoformat(iso.replace(" ", "T")).replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return None


def _derive_dispatches_from_events(run_id: int, phase: str | None) -> list[dict]:
    """Reconstruct synthetic dispatch rows from agent events for runs whose
    workspace was provisioned before commit 5c46451 (when the SERIALIZED
    dispatcher.sh / fetch_batch_to_file.sh started emitting structured
    dispatch_start / case_done events). Pairs '<X> start' events with the
    next '<X> summary' event from the same agent to produce a coarse
    per-batch dispatch history. Without this fallback the AgentsPanel UI
    shows zero expandable rows for every old run, and the user can't see
    that subagents WERE dispatched (the data lives in events but never
    reached the dispatches table)."""
    events = db.list_events_for_run(run_id)
    open_starts: dict[str, list] = {}  # agent -> stack of unmatched start events
    completed: list[dict] = []
    for ev in events:
        agent = (ev.agent_name or "").strip()
        if agent in _INFRA_AGENTS:
            continue
        s = (ev.summary or "").strip().lower()
        if s.endswith(" start"):
            open_starts.setdefault(agent, []).append(ev)
        elif s.endswith(" summary"):
            stack = open_starts.get(agent) or []
            if not stack:
                continue
            start_ev = stack.pop()
            completed.append({
                "id": f"derived-{start_ev.id}",
                "phase": start_ev.phase or "consume",
                "round": 0,
                "agent": agent,
                "slot": "derived",
                "task": start_ev.summary,
                "state": "done",
                "started_at": _iso_to_epoch(start_ev.created_at),
                "finished_at": _iso_to_epoch(ev.created_at),
                "error": None,
            })
    # Unmatched starts → still-running rows
    for agent, stack in open_starts.items():
        for start_ev in stack:
            completed.append({
                "id": f"derived-{start_ev.id}",
                "phase": start_ev.phase or "consume",
                "round": 0,
                "agent": agent,
                "slot": "derived",
                "task": start_ev.summary,
                "state": "running",
                "started_at": _iso_to_epoch(start_ev.created_at),
                "finished_at": None,
                "error": None,
            })
    if phase:
        completed = [d for d in completed if d.get("phase") == phase]
    completed.sort(key=lambda d: (d.get("started_at") is None, d.get("started_at") or 0))
    return completed


@router.get("")
def list_dispatches(
    project_id: int,
    run_id: int,
    current_user: CurrentUser,
    phase: str | None = None,
) -> list[dict]:
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    rows = [_serialize(d) for d in db.list_dispatches(run.id, phase=phase)]
    if not rows:
        rows = _derive_dispatches_from_events(run.id, phase)
    return rows
