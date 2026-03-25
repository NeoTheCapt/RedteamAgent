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


def _phase_for_event(event: Event) -> str:
    if event.phase != "unknown":
        return event.phase

    agent_phase = {
        "recon-specialist": "recon",
        "source-analyzer": "recon",
        "vulnerability-analyst": "consume-test",
        "exploit-developer": "exploit",
        "osint-analyst": "exploit",
        "report-writer": "report",
    }
    if event.agent_name in agent_phase:
        return agent_phase[event.agent_name]
    if event.agent_name == "operator" and event.summary == "Engagement start":
        return "recon"
    return "unknown"


def _project_timeline_events(events: list[Event]) -> list[Event]:
    projected: list[Event] = []
    next_id = -1
    seen_phase_started: set[str] = {
        event.phase for event in events if event.event_type == "phase.started" and event.phase != "unknown"
    }

    for event in events:
        if event.event_type != "artifact.updated" or event.task_name != "log.md":
            continue

        phase = _phase_for_event(event)
        if phase != "unknown" and phase not in seen_phase_started:
            projected.append(
                Event(
                    id=next_id,
                    run_id=event.run_id,
                    event_type="phase.started",
                    phase=phase,
                    task_name=phase,
                    agent_name="operator",
                    summary=f"{phase} phase started",
                    created_at=event.created_at,
                )
            )
            next_id -= 1
            seen_phase_started.add(phase)

        normalized = event.summary.lower()
        if event.agent_name == "operator":
            continue
        if normalized.endswith(" start"):
            projected.append(
                Event(
                    id=next_id,
                    run_id=event.run_id,
                    event_type="task.started",
                    phase=phase,
                    task_name=event.agent_name,
                    agent_name=event.agent_name,
                    summary=event.summary,
                    created_at=event.created_at,
                )
            )
            next_id -= 1
        elif normalized.endswith(" summary") or normalized.endswith(" complete"):
            projected.append(
                Event(
                    id=next_id,
                    run_id=event.run_id,
                    event_type="task.completed",
                    phase=phase,
                    task_name=event.agent_name,
                    agent_name=event.agent_name,
                    summary=event.summary,
                    created_at=event.created_at,
                )
            )
            next_id -= 1

    merged = sorted([*events, *projected], key=lambda item: (item.created_at, item.id))
    return merged


def list_events_for_run(project_id: int, run_id: int, user: User) -> list[Event]:
    run = _run_or_404(project_id, run_id, user)
    return _project_timeline_events(db.list_events_for_run(run.id))


def summarize_events_for_run(project_id: int, run_id: int, user: User) -> dict[str, dict[str, str] | None]:
    events = list_events_for_run(project_id, run_id, user)
    latest_phase = next((event for event in reversed(events) if event.event_type.startswith("phase.")), None)
    latest_task = next((event for event in reversed(events) if event.event_type.startswith("task.")), None)

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
