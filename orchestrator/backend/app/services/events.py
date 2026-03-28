from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

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


def _phase_for_event(event: Event, current_phase: str = "unknown") -> str:
    if event.phase != "unknown":
        return event.phase

    if event.agent_name == "operator" and event.summary == "Engagement start":
        return "recon"
    if current_phase != "unknown":
        return current_phase

    agent_phase = {
        "recon-specialist": "recon",
        "vulnerability-analyst": "consume-test",
        "exploit-developer": "exploit",
        "osint-analyst": "exploit",
        "report-writer": "report",
    }
    if event.agent_name in agent_phase:
        return agent_phase[event.agent_name]
    return "unknown"


def _project_timeline_events(events: list[Event]) -> list[Event]:
    projected: list[Event] = []
    next_id = -1
    seen_phase_started: set[str] = {
        event.phase for event in events if event.event_type == "phase.started" and event.phase != "unknown"
    }
    current_phase = "unknown"

    for event in events:
        phase = _phase_for_event(event, current_phase)
        if phase != "unknown":
            current_phase = phase

        if event.event_type != "artifact.updated" or event.task_name != "log.md":
            continue
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


def _normalize_phase_name(phase: str | None) -> str:
    if not phase:
        return "unknown"
    normalized = phase.strip().lower().replace("_", "-").replace("&", "and")
    mapping = {
        "recon": "recon",
        "collect": "collect",
        "consume-test": "consume-test",
        "consume-and-test": "consume-test",
        "test": "consume-test",
        "exploit": "exploit",
        "report": "report",
    }
    return mapping.get(normalized, "unknown")


def _active_engagement_root(run_root: Path) -> Path | None:
    workspace = run_root / "workspace"
    engagements_root = workspace / "engagements"
    active_file = engagements_root / ".active"
    if active_file.exists():
        active_name = active_file.read_text(encoding="utf-8").strip()
        if active_name:
            active_relative = active_name.removeprefix("./").removeprefix("/")
            candidate = workspace / active_relative if active_relative.startswith("engagements/") else engagements_root / active_relative
            if candidate.exists():
                return candidate
    candidates = sorted([path for path in engagements_root.iterdir() if path.is_dir()], reverse=True) if engagements_root.exists() else []
    return candidates[0] if candidates else None


def _scope_phase_for_run(run_root: Path) -> str:
    engagement_root = _active_engagement_root(run_root)
    if engagement_root is None:
        return "unknown"
    scope_path = engagement_root / "scope.json"
    if not scope_path.exists():
        return "unknown"
    try:
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "unknown"
    return _normalize_phase_name(scope.get("current_phase"))


def _project_process_log_events(run_id: int, run_root: Path, events: list[Event]) -> list[Event]:
    process_log = run_root / "runtime" / "process.log"
    if not process_log.exists():
        return events

    projected: list[Event] = []
    next_id = -100000
    scope_phase = _scope_phase_for_run(run_root)
    seen = {
        (event.event_type, event.agent_name, event.summary, event.created_at)
        for event in events
        if event.agent_name and event.event_type.startswith("task.")
    }

    def add_projected(event_type: str, phase: str, task_name: str, agent_name: str, summary: str, created_at: str) -> None:
        nonlocal next_id
        key = (event_type, agent_name, summary, created_at)
        if key in seen:
            return
        projected.append(
            Event(
                id=next_id,
                run_id=run_id,
                event_type=event_type,
                phase=phase,
                task_name=task_name,
                agent_name=agent_name,
                summary=summary,
                created_at=created_at,
            )
        )
        seen.add(key)
        next_id += 1

    for line in process_log.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "tool_use":
            continue

        part = payload.get("part") or {}
        tool_name = part.get("tool")
        state = part.get("state") or {}
        created_at = datetime.fromtimestamp(
            (payload.get("timestamp") or 0) / 1000,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")

        if tool_name != "task":
            summary = (
                state.get("input", {}).get("description")
                or part.get("title")
                or f"{tool_name} activity"
            )
            task_name = tool_name or "tool"
            add_projected("task.started", scope_phase, task_name, "operator", summary, created_at)
            add_projected(
                "task.completed",
                scope_phase,
                task_name,
                "operator",
                f"{summary} completed",
                created_at,
            )
            continue

        task_input = state.get("input") or {}
        agent_name = task_input.get("subagent_type")
        if not agent_name:
            continue

        prompt = task_input.get("prompt") or ""
        phase_match = re.search(r"\*\*Phase\*\*:\s*([A-Za-z& -]+)", prompt)
        phase = _normalize_phase_name(phase_match.group(1) if phase_match else None)
        summary = task_input.get("description") or f"{agent_name} task"

        add_projected("task.started", phase, agent_name, agent_name, summary, created_at)
        add_projected(
            "task.completed",
            phase,
            agent_name,
            agent_name,
            f"{summary} completed",
            created_at,
        )

    if not projected:
        return events
    return sorted([*events, *projected], key=lambda item: (item.created_at, item.id))


def list_events_for_run(project_id: int, run_id: int, user: User) -> list[Event]:
    run = _run_or_404(project_id, run_id, user)
    run_root = Path(run.engagement_root)
    events = _project_timeline_events(db.list_events_for_run(run.id))
    return _project_process_log_events(run.id, run_root, events)


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
