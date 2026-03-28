from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import HTTPException, status

from ..models.user import User
from .events import list_events_for_run
from .runs import _project_or_404, _reconcile_run_status

PHASE_ORDER = ["recon", "collect", "consume-test", "exploit", "report"]
PHASE_LABELS = {
    "recon": "Recon",
    "collect": "Collect",
    "consume-test": "Consume & Test",
    "exploit": "Exploit",
    "report": "Report",
}
HIGH_RISK_SURFACES = {"account_recovery", "dynamic_render", "object_reference", "privileged_write"}
AGENT_PHASES = {
    "operator": "unknown",
    "recon-specialist": "recon",
    "source-analyzer": "recon",
    "vulnerability-analyst": "consume-test",
    "exploit-developer": "exploit",
    "osint-analyst": "exploit",
    "report-writer": "report",
}
DEFAULT_SUBAGENT_ROSTER = tuple(AGENT_PHASES.keys())
TERMINAL_RUN_STATUSES = {"failed", "completed"}


@dataclass(frozen=True, slots=True)
class RunSummary:
    target: dict
    overview: dict
    runtime_model: dict
    coverage: dict
    current: dict
    phases: list[dict]
    agents: list[dict]


@dataclass(frozen=True, slots=True)
class ObservedPathRecord:
    method: str
    url: str
    type: str
    status: str
    assigned_agent: str
    source: str


def _run_or_404(project_id: int, run_id: int, user: User):
    project = _project_or_404(project_id, user)
    from .. import db

    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _reconcile_run_status(run)


def _active_engagement_root(run_root: Path) -> Path:
    engagements_root = run_root / "workspace" / "engagements"
    active_file = run_root / "workspace" / "engagements" / ".active"
    if not active_file.exists():
        candidates = sorted([path for path in engagements_root.iterdir() if path.is_dir()], reverse=True) if engagements_root.exists() else []
        if candidates:
            active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
            return candidates[0]
        return run_root

    active_name = active_file.read_text(encoding="utf-8").strip()
    if not active_name:
        return run_root

    active_relative = active_name.removeprefix("./").removeprefix("/")
    if active_relative.startswith("engagements/"):
        candidate = run_root / "workspace" / active_relative
    else:
        candidate = run_root / "workspace" / "engagements" / active_relative
    if candidate.exists():
        return candidate
    candidates = sorted([path for path in engagements_root.iterdir() if path.is_dir()], reverse=True) if engagements_root.exists() else []
    if candidates:
        active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
        return candidates[0]
    return run_root


def _cases_db_candidates(run_root: Path, active_root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(path)

    add(active_root / "cases.db")
    add(run_root / "workspace" / "cases.db")

    engagements_root = run_root / "workspace" / "engagements"
    if engagements_root.exists():
        for path in sorted(engagements_root.glob("*/cases.db"), reverse=True):
            add(path)

    return candidates


def _is_sqlite_transient_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("locked", "busy", "database schema is locked"))


def _connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.execute("PRAGMA busy_timeout = 1000")
    return connection


def _copy_sqlite_snapshot(path: Path, snapshot_dir: Path) -> Path:
    snapshot_path = snapshot_dir / path.name
    shutil.copy2(path, snapshot_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, snapshot_dir / sidecar.name)
    return snapshot_path


def _read_sqlite_with_fallback(path: Path, reader, default):
    if not path.exists():
        return default

    for _ in range(5):
        try:
            with sqlite3.connect(path, timeout=1.0) as connection:
                connection.execute("PRAGMA busy_timeout = 1000")
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc):
                return default
        except sqlite3.Error:
            return default

        try:
            with _connect_sqlite_readonly(path) as connection:
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc):
                return default
        except sqlite3.Error:
            return default

        time.sleep(0.1)

    try:
        with tempfile.TemporaryDirectory(prefix="run-summary-sqlite-") as temp_dir:
            snapshot_path = _copy_sqlite_snapshot(path, Path(temp_dir))
            with _connect_sqlite_readonly(snapshot_path) as connection:
                return reader(connection)
    except (OSError, sqlite3.Error):
        return default


def _count_cases_for_db(path: Path) -> int:
    rows = _read_sqlite_with_fallback(path, lambda connection: connection.execute("SELECT COUNT(*) FROM cases").fetchone(), None)
    if not rows:
        return -1
    return int(rows[0] or 0)


def _resolve_cases_db(run_root: Path, active_root: Path) -> Path:
    candidates = _cases_db_candidates(run_root, active_root)
    if not candidates:
        return active_root / "cases.db"

    preferred = candidates[0]
    preferred_count = _count_cases_for_db(preferred)
    if preferred_count > 0:
        return preferred

    ranked = sorted(
        ((path, _count_cases_for_db(path)) for path in candidates),
        key=lambda item: (item[1], 1 if item[0] == preferred else 0, item[0].as_posix()),
        reverse=True,
    )
    best_path, best_count = ranked[0]
    if best_count >= 0:
        return best_path
    return preferred


def _normalize_phase(phase: str | None) -> str:
    if not phase:
        return "unknown"
    normalized = phase.strip().lower().replace("_", "-")
    if normalized == "complete":
        return "report"
    if normalized == "consume-test":
        return normalized
    if normalized == "test":
        return "consume-test"
    return normalized


def _event_phase(event) -> str:
    phase = _normalize_phase(getattr(event, "phase", "unknown"))
    if phase != "unknown":
        return phase
    return AGENT_PHASES.get(getattr(event, "agent_name", ""), "unknown")


def _is_terminal_run_status(run_status: str) -> bool:
    return run_status in TERMINAL_RUN_STATUSES


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _count_findings(path: Path) -> int:
    if not path.exists():
        return 0
    content = path.read_text(encoding="utf-8")
    return len(re.findall(r"^## \[FINDING-[A-Z]+-\d+\]", content, flags=re.MULTILINE))


def _load_cases_metrics(path: Path) -> dict:
    metrics = {
        "total_cases": 0,
        "completed_cases": 0,
        "pending_cases": 0,
        "processing_cases": 0,
        "error_cases": 0,
        "case_types": [],
        "processing_agents": [],
    }
    if not path.exists():
        return metrics

    def _reader(connection: sqlite3.Connection):
        type_rows = connection.execute(
            "SELECT type, status, COUNT(*) AS count FROM cases GROUP BY type, status"
        ).fetchall()
        column_rows = connection.execute("PRAGMA table_info(cases)").fetchall()
        column_names = {str(row[1]) for row in column_rows}
        if "assigned_agent" in column_names:
            processing_rows = connection.execute(
                "SELECT assigned_agent, COUNT(*) AS count FROM cases WHERE status = 'processing' AND assigned_agent IS NOT NULL AND assigned_agent != '' GROUP BY assigned_agent"
            ).fetchall()
        else:
            processing_rows = []
        return type_rows, processing_rows

    payload = _read_sqlite_with_fallback(path, _reader, None)
    if payload is None:
        return metrics

    rows, processing_rows = payload
    type_rows: dict[str, Counter] = defaultdict(Counter)
    for case_type, status_name, count in rows:
        type_rows[case_type][status_name] += count
        metrics["total_cases"] += count
        if status_name == "done":
            metrics["completed_cases"] += count
        elif status_name == "pending":
            metrics["pending_cases"] += count
        elif status_name == "processing":
            metrics["processing_cases"] += count
        elif status_name == "error":
            metrics["error_cases"] += count

    metrics["case_types"] = [
        {
            "type": case_type,
            "total": sum(counter.values()),
            "done": counter.get("done", 0),
            "pending": counter.get("pending", 0),
            "processing": counter.get("processing", 0),
            "error": counter.get("error", 0),
        }
        for case_type, counter in sorted(type_rows.items(), key=lambda item: (-sum(item[1].values()), item[0]))
    ]
    metrics["processing_agents"] = [
        {"agent_name": agent_name, "count": count}
        for agent_name, count in processing_rows
    ]
    return metrics


def _load_observed_paths(path: Path) -> list[ObservedPathRecord]:
    if not path.exists():
        return []

    def _reader(connection: sqlite3.Connection):
        column_rows = connection.execute("PRAGMA table_info(cases)").fetchall()
        column_names = [str(row[1]) for row in column_rows]
        if not column_names:
            return [], []

        selected = [name for name in ("method", "url", "type", "status", "assigned_agent", "source") if name in column_names]
        if not selected:
            return [], []

        query = (
            f"SELECT {', '.join(selected)} "
            "FROM cases "
            "ORDER BY "
            "CASE WHEN status = 'processing' THEN 0 WHEN status = 'pending' THEN 1 WHEN status = 'done' THEN 2 ELSE 3 END, "
            "type, "
            "url"
        )
        rows = connection.execute(query).fetchall()
        return selected, rows

    payload = _read_sqlite_with_fallback(path, _reader, None)
    if payload is None:
        return []

    selected, rows = payload
    records: list[ObservedPathRecord] = []
    for row in rows:
        payload = dict(zip(selected, row, strict=False))
        url = str(payload.get("url") or "").strip()
        if not url:
            continue
        records.append(
            ObservedPathRecord(
                method=str(payload.get("method") or "GET").strip() or "GET",
                url=url,
                type=str(payload.get("type") or "unknown").strip() or "unknown",
                status=str(payload.get("status") or "unknown").strip() or "unknown",
                assigned_agent=str(payload.get("assigned_agent") or "").strip(),
                source=str(payload.get("source") or "").strip(),
            )
        )
    return records


def _load_surface_metrics(path: Path) -> dict:
    metrics = {
        "total_surfaces": 0,
        "remaining_surfaces": 0,
        "high_risk_remaining": 0,
        "surface_statuses": {},
        "surface_types": [],
    }
    if not path.exists():
        return metrics

    status_counts: Counter = Counter()
    type_counts: Counter = Counter()
    high_risk_remaining = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        status_name = payload.get("status", "unknown")
        surface_type = payload.get("surface_type", "unknown")
        status_counts[status_name] += 1
        type_counts[surface_type] += 1
        metrics["total_surfaces"] += 1
        if status_name not in {"covered", "not_applicable"}:
            metrics["remaining_surfaces"] += 1
            if surface_type in HIGH_RISK_SURFACES:
                high_risk_remaining += 1

    metrics["high_risk_remaining"] = high_risk_remaining
    metrics["surface_statuses"] = dict(sorted(status_counts.items()))
    metrics["surface_types"] = [
        {"type": surface_type, "count": count}
        for surface_type, count in type_counts.most_common()
    ]
    return metrics


def _latest_active_task_phase(events: list, scope_phase: str) -> str:
    active_tasks: dict[str, object] = {}
    for event in events:
        if not getattr(event, "event_type", "").startswith("task."):
            continue
        key = getattr(event, "agent_name", "")
        if not key:
            continue
        if event.event_type == "task.started":
            active_tasks[key] = event
        elif event.event_type == "task.completed":
            active_tasks.pop(key, None)

    if not active_tasks:
        return "unknown"

    latest_active = max(active_tasks.values(), key=lambda item: (item.created_at, item.id))
    return _resolved_event_phase(latest_active, scope_phase)


def _effective_current_phase(scope: dict, events: list, run_status: str) -> str:
    scope_phase = _normalize_phase(scope.get("current_phase")) if scope else "unknown"
    if _is_terminal_run_status(run_status):
        return scope_phase

    active_task_phase = _latest_active_task_phase(events, scope_phase)
    if active_task_phase != "unknown":
        return active_task_phase

    latest_runtime_phase = next(
        (
            _event_phase(event)
            for event in reversed(events)
            if getattr(event, "event_type", "") in {"phase.started", "phase.completed"} and _event_phase(event) != "unknown"
        ),
        "unknown",
    )
    if latest_runtime_phase != "unknown":
        return latest_runtime_phase

    latest_task_phase = next(
        (
            _resolved_event_phase(event, scope_phase)
            for event in reversed(events)
            if getattr(event, "event_type", "").startswith("task.")
            and _resolved_event_phase(event, scope_phase) != "unknown"
        ),
        "unknown",
    )
    if latest_task_phase != "unknown":
        return latest_task_phase

    return scope_phase


def _build_phase_cards(scope: dict, events: list, agents: list[dict], run_status: str, effective_current_phase: str) -> list[dict]:
    completed = {_normalize_phase(item) for item in scope.get("phases_completed", [])}
    task_counts: Counter = Counter()
    latest_summary: dict[str, str] = {}
    terminal = _is_terminal_run_status(run_status)

    for event in events:
        phase = _event_phase(event)
        if phase == "unknown":
            continue
        if getattr(event, "event_type", "").startswith("task."):
            task_counts[phase] += 1
            latest_summary[phase] = getattr(event, "summary", "")
        elif getattr(event, "event_type", "") == "phase.completed":
            latest_summary[phase] = getattr(event, "summary", "")
        elif getattr(event, "event_type", "") == "phase.started":
            latest_summary.setdefault(phase, getattr(event, "summary", ""))

    active_agents_by_phase: Counter = Counter()
    if not terminal:
        for agent in agents:
            if agent["status"] == "active":
                active_agents_by_phase[agent["phase"]] += 1

    cards: list[dict] = []
    for phase in PHASE_ORDER:
        if phase in completed:
            state = "completed"
        elif terminal:
            state = "pending"
        elif phase == effective_current_phase:
            state = "active"
        else:
            state = "pending"

        cards.append(
            {
                "phase": phase,
                "label": PHASE_LABELS[phase],
                "state": state,
                "task_events": task_counts.get(phase, 0),
                "active_agents": active_agents_by_phase.get(phase, 0),
                "latest_summary": latest_summary.get(phase, ""),
            }
        )
    return cards


def _resolved_event_phase(event, scope_phase: str) -> str:
    explicit_phase = _normalize_phase(getattr(event, "phase", "unknown"))
    if explicit_phase != "unknown":
        return explicit_phase
    if scope_phase != "unknown":
        return scope_phase
    return _event_phase(event)


def _build_agent_cards(
    events: list,
    scope: dict,
    processing_agents: list[dict] | None = None,
    run_status: str = "running",
) -> list[dict]:
    scope_phase = _normalize_phase(scope.get("current_phase")) if scope else "unknown"
    latest_by_agent: dict[str, object] = {}
    terminal = _is_terminal_run_status(run_status)
    for event in events:
        agent_name = getattr(event, "agent_name", "")
        if not agent_name or agent_name == "launcher":
            continue
        latest_by_agent[agent_name] = event

    cards: list[dict] = []
    for agent_name, event in sorted(latest_by_agent.items(), key=lambda item: item[0]):
        event_type = getattr(event, "event_type", "")
        status_name = "idle"
        if terminal:
            if event_type == "task.completed":
                status_name = "completed"
        else:
            if event_type == "task.started":
                status_name = "active"
            elif event_type == "task.completed":
                status_name = "completed"
            elif _event_phase(event) != "unknown":
                status_name = "active"

        cards.append(
            {
                "agent_name": agent_name,
                "phase": _resolved_event_phase(event, scope_phase),
                "status": status_name,
                "task_name": getattr(event, "task_name", ""),
                "summary": getattr(event, "summary", ""),
                "updated_at": getattr(event, "created_at", ""),
            }
        )

    if not terminal:
        for processing in processing_agents or []:
            agent_name = processing["agent_name"]
            existing = next((card for card in cards if card["agent_name"] == agent_name), None)
            if existing and existing["status"] == "active":
                continue
            payload = {
                "agent_name": agent_name,
                "phase": AGENT_PHASES.get(agent_name, "unknown"),
                "status": "active",
                "task_name": agent_name,
                "summary": f"Processing {processing['count']} queued case(s)",
                "updated_at": "",
            }
            if existing:
                existing.update(payload)
            else:
                cards.append(payload)

    existing_names = {card["agent_name"] for card in cards}
    for agent_name in DEFAULT_SUBAGENT_ROSTER:
        if agent_name in existing_names:
            continue
        cards.append(
            {
                "agent_name": agent_name,
                "phase": AGENT_PHASES.get(agent_name, "unknown"),
                "status": "idle",
                "task_name": "",
                "summary": "No activity yet.",
                "updated_at": "",
            }
        )

    cards.sort(key=lambda item: item["agent_name"])
    return cards


def _current_activity(events: list, scope: dict, run_status: str, stop_reason_text: str = "") -> dict:
    scope_phase = _normalize_phase(scope.get("current_phase")) if scope else "unknown"
    if _is_terminal_run_status(run_status):
        terminal_summary = stop_reason_text.strip() or (
            "Run completed successfully." if run_status == "completed" else "Run failed."
        )
        return {
            "phase": scope_phase,
            "task_name": "",
            "agent_name": "",
            "summary": terminal_summary,
        }

    active_tasks: dict[str, object] = {}
    for event in events:
        if not getattr(event, "event_type", "").startswith("task."):
            continue
        key = getattr(event, "agent_name", "")
        if not key:
            continue
        if event.event_type == "task.started":
            active_tasks[key] = event
        elif event.event_type == "task.completed":
            active_tasks.pop(key, None)

    if active_tasks:
        latest_active = max(active_tasks.values(), key=lambda item: (item.created_at, item.id))
        return {
            "phase": _resolved_event_phase(latest_active, scope_phase),
            "task_name": getattr(latest_active, "task_name", ""),
            "agent_name": getattr(latest_active, "agent_name", ""),
            "summary": getattr(latest_active, "summary", "Waiting for events"),
        }

    latest_task = next((event for event in reversed(events) if event.event_type.startswith("task.")), None)
    latest_phase = next((event for event in reversed(events) if event.event_type.startswith("phase.")), None)
    return {
        "phase": scope_phase if scope_phase != "unknown" else _event_phase(latest_phase) if latest_phase else "unknown",
        "task_name": getattr(latest_task, "task_name", "") if latest_task else "",
        "agent_name": getattr(latest_task, "agent_name", "") if latest_task else "",
        "summary": getattr(latest_task or latest_phase, "summary", "Waiting for events"),
    }


def _build_target_card(run, scope: dict, active_root: Path) -> dict:
    parsed = urlparse(run.target)
    hostname = scope.get("hostname") or parsed.hostname or run.target
    display_path = parsed.path or "/"
    raw_scope_entries = scope.get("scope", [])
    if isinstance(raw_scope_entries, dict):
        scope_entries = [
            *[str(item) for item in raw_scope_entries.get("in_scope", [])],
            *[str(item) for item in raw_scope_entries.get("out_of_scope", [])],
        ]
    elif isinstance(raw_scope_entries, list):
        scope_entries = [str(item) for item in raw_scope_entries]
    else:
        scope_entries = []
    target_status = scope.get("status") or run.status
    if run.status in {"failed", "completed"}:
        target_status = run.status
    return {
        "target": run.target,
        "hostname": hostname,
        "scheme": parsed.scheme or "https",
        "path": display_path,
        "port": scope.get("port") or parsed.port or (443 if parsed.scheme == "https" else 80),
        "scope_entries": scope_entries,
        "engagement_dir": str(active_root),
        "started_at": scope.get("start_time") or run.created_at,
        "status": target_status,
    }


def _load_runtime_model_verification(run_root: Path, project) -> dict:
    process_log = run_root / "runtime" / "process.log"
    observed_provider = ""
    observed_model = ""
    if process_log.exists():
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
            metadata = (((payload.get("part") or {}).get("state") or {}).get("metadata") or {})
            model = metadata.get("model") or {}
            provider = str(model.get("providerID") or "").strip()
            model_id = str(model.get("modelID") or "").strip()
            if provider or model_id:
                observed_provider = provider
                observed_model = model_id
                break

    configured_provider = project.provider_id.strip()
    configured_model = project.model_id.strip()
    configured_small_model = project.small_model_id.strip()
    status = "pending"
    summary = "Waiting for runtime model metadata."

    if observed_provider or observed_model:
        status = "matched"
        summary = f"Observed provider={observed_provider or 'unknown'} model={observed_model or 'unknown'}."
        if configured_provider and observed_provider and configured_provider != observed_provider:
            status = "mismatch"
        if configured_model and observed_model and configured_model != observed_model:
            status = "mismatch"
        if status == "mismatch":
            summary = (
                f"Configured provider={configured_provider or 'unset'} model={configured_model or 'unset'}, "
                f"but observed provider={observed_provider or 'unknown'} model={observed_model or 'unknown'}."
            )
    elif configured_provider or configured_model or configured_small_model:
        summary = (
            f"Configured provider={configured_provider or 'unset'} model={configured_model or 'unset'}; "
            "runtime metadata not observed yet."
        )

    return {
        "configured_provider": configured_provider,
        "configured_model": configured_model,
        "configured_small_model": configured_small_model,
        "observed_provider": observed_provider,
        "observed_model": observed_model,
        "status": status,
        "summary": summary,
    }


def summarize_run(project_id: int, run_id: int, user: User) -> RunSummary:
    run = _run_or_404(project_id, run_id, user)
    project = _project_or_404(project_id, user)
    run_root = Path(run.engagement_root)
    active_root = _active_engagement_root(run_root)
    cases_db = _resolve_cases_db(run_root, active_root)
    scope = _load_json(active_root / "scope.json")
    run_metadata = _load_json(run_root / "run.json")
    cases = _load_cases_metrics(cases_db)
    surfaces = _load_surface_metrics(active_root / "surfaces.jsonl")
    findings_count = _count_findings(active_root / "findings.md")
    events = list_events_for_run(project_id, run_id, user)
    effective_current_phase = _effective_current_phase(scope, events, run.status)
    agents = _build_agent_cards(events, scope, cases.get("processing_agents", []), run.status)
    phases = _build_phase_cards(scope, events, agents, run.status, effective_current_phase)

    latest_task = next((event for event in reversed(events) if event.event_type.startswith("task.")), None)
    latest_phase = next((event for event in reversed(events) if event.event_type.startswith("phase.")), None)
    current = _current_activity(events, scope, run.status, str(run_metadata.get("stop_reason_text", "")))

    return RunSummary(
        target=_build_target_card(run, scope, active_root),
        overview={
            "findings_count": findings_count,
            "active_agents": 0 if _is_terminal_run_status(run.status) else sum(1 for agent in agents if agent["status"] == "active"),
            "available_agents": len(agents),
            "current_phase": effective_current_phase,
            "updated_at": run.updated_at if _is_terminal_run_status(run.status) else getattr(latest_task or latest_phase, "created_at", run.updated_at),
        },
        runtime_model=_load_runtime_model_verification(run_root, project),
        coverage={
            **cases,
            **surfaces,
        },
        current=current,
        phases=phases,
        agents=agents,
    )


def list_observed_paths(project_id: int, run_id: int, user: User) -> list[ObservedPathRecord]:
    run = _run_or_404(project_id, run_id, user)
    run_root = Path(run.engagement_root)
    active_root = _active_engagement_root(run_root)
    return _load_observed_paths(_resolve_cases_db(run_root, active_root))
