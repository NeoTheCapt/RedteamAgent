from __future__ import annotations

from fastapi import HTTPException, status

from .. import db
from ..models.event import Event
from ..models.user import User
from .runs import _project_or_404


def _run_or_404(project_id: int, run_id: int, user: User):
    project = _project_or_404(project_id, user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def create_event_for_run(
    project_id: int,
    run_id: int,
    user: User,
    *,
    event_type: str,
    phase: str,
    task_name: str,
    agent_name: str,
    summary: str,
) -> Event:
    run = _run_or_404(project_id, run_id, user)
    return db.create_event(run.id, event_type, phase, task_name, agent_name, summary)


def list_events_for_run(project_id: int, run_id: int, user: User) -> list[Event]:
    run = _run_or_404(project_id, run_id, user)
    return db.list_events_for_run(run.id)


def summarize_events_for_run(project_id: int, run_id: int, user: User) -> dict[str, dict[str, str] | None]:
    run = _run_or_404(project_id, run_id, user)
    latest_phase = db.get_latest_event_for_run(run.id, prefix="phase.")
    latest_task = db.get_latest_event_for_run(run.id, prefix="task.")

    return {
        "latest_phase": (
            {
                "phase": latest_phase.phase,
                "event_type": latest_phase.event_type,
                "summary": latest_phase.summary,
            }
            if latest_phase
            else None
        ),
        "latest_task": (
            {
                "phase": latest_task.phase,
                "task_name": latest_task.task_name,
                "event_type": latest_task.event_type,
                "summary": latest_task.summary,
            }
            if latest_task
            else None
        ),
    }
