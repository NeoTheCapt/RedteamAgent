from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, status

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.run import Run
from ..models.user import User
from .launcher import (
    RUNTIME_PID_LOOKUP_UNAVAILABLE,
    _active_engagement_dir,
    _clear_run_terminal_reason,
    _continuous_observation_report_hold_active,
    _last_logged_stop_metadata,
    _latest_process_log_activity_at,
    _latest_undispatched_batch_fetch,
    _latest_unresolved_permission_request_at,
    _maybe_auto_resume_run,
    _start_container_supervisor,
    _write_run_terminal_reason,
    engagement_completion_state,
    locate_runtime_pid,
    normalize_active_scope,
    opencode_home_root_for,
    prepare_run_runtime,
    process_log_path_for,
    process_metadata_path_for,
    start_run_runtime,
    stop_run_runtime,
    _active_runtime_agents,
    _active_runtime_metadata_agents,
    _latest_runtime_metadata_activity_at,
    _run_metadata_has_current_task,
    _stale_processing_agents,
    _auto_resume_stall_guard_active,
)

ALLOWED_STATUSES = {"queued", "running", "completed", "failed", "stopped"}
RUN_STARTUP_GRACE_SECONDS = 90
# The local fixed-target optimization loop only treats a live run as stale after
# 15 minutes of confirmed buggy behavior. Keep the backend watchdog aligned with
# that contract so long-running consume-test work is not failed a full cycle too
# early.
RUN_STALL_TIMEOUT_SECONDS = 900
PROCESSING_AGENT_MISMATCH_GRACE_SECONDS = 120
PENDING_QUEUE_DISPATCH_GRACE_SECONDS = 120
PERMISSION_REQUEST_GRACE_SECONDS = 60
# Real targets can spend several minutes in autonomous initialization/recon before the
# first queue item or observed path lands. Keep the early watchdog long enough to avoid
# killing active slow-start recon just as the first subagent/task dispatch begins.
EARLY_PHASE_STALL_TIMEOUT_SECONDS = 300
EARLY_PHASE_STALL_PHASES = {"unknown", "recon", "collect"}


def _is_sqlite_corruption_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("malformed", "not a database", "disk image is malformed"))


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


def _read_sqlite_snapshot(path: Path, reader, default):
    try:
        with tempfile.TemporaryDirectory(prefix="runs-sqlite-") as temp_dir:
            snapshot_path = _copy_sqlite_snapshot(path, Path(temp_dir))
            with _connect_sqlite_readonly(snapshot_path) as connection:
                return reader(connection)
    except (OSError, sqlite3.Error):
        return default


def _read_sqlite_with_fallback(path: Path, reader, default):
    if not path.exists():
        return default

    for _ in range(5):
        try:
            with sqlite3.connect(path, timeout=1.0) as connection:
                connection.execute("PRAGMA busy_timeout = 1000")
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc) and not _is_sqlite_corruption_error(exc):
                return default
        except sqlite3.Error as exc:
            if not _is_sqlite_corruption_error(exc):
                return default

        try:
            with _connect_sqlite_readonly(path) as connection:
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc) and not _is_sqlite_corruption_error(exc):
                return default
        except sqlite3.Error as exc:
            if not _is_sqlite_corruption_error(exc):
                return default

        snapshot_value = _read_sqlite_snapshot(path, reader, default)
        if snapshot_value is not default:
            return snapshot_value

        time.sleep(0.1)

    return default


def _project_or_404(project_id: int, user: User) -> Project:
    project = db.get_project_by_id(project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def run_root_for(project: Project, run_id: int) -> Path:
    return Path(project.root_path) / "runs" / f"run-{run_id:04d}"


def create_run_for_project(project_id: int, user: User, target: str) -> Run:
    project = _project_or_404(project_id, user)
    stub = db.create_run(project.id, target.strip(), "queued", "")
    run_root = run_root_for(project, stub.id)
    run_root.mkdir(parents=True, exist_ok=True)
    run = db.update_run_engagement_root(stub.id, str(run_root))
    prepare_run_runtime(project, run)
    if settings.auto_launch_runs:
        return start_run_runtime(project, run, user)
    return run


def _parse_db_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _active_scope_path(run: Run) -> Path | None:
    workspace = Path(run.engagement_root) / "workspace"
    engagement_dir = workspace / "engagements"
    active_file = engagement_dir / ".active"
    if active_file.exists():
        active_name = active_file.read_text(encoding="utf-8").strip()
        if active_name:
            active_path = Path(active_name)
            if active_path.is_absolute():
                scope_path = active_path / "scope.json"
            else:
                active_relative = active_name.removeprefix("./").removeprefix("/")
                scope_path = (
                    workspace / active_relative / "scope.json"
                    if active_relative.startswith("engagements/")
                    else engagement_dir / active_relative / "scope.json"
                )
            if scope_path.exists():
                return scope_path

    candidates = (
        sorted(
            [path for path in engagement_dir.iterdir() if path.is_dir() and (path / "scope.json").exists()],
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        if engagement_dir.exists()
        else []
    )
    return candidates[0] / "scope.json" if candidates else None


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc_datetime_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=None)


def _path_mtime(path: Path) -> datetime | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return _utc_datetime_from_timestamp(path.stat().st_mtime)
    except OSError:
        return None


def _latest_runtime_activity_at(run: Run) -> datetime | None:
    latest_timestamp = _latest_process_log_activity_at(process_log_path_for(run))
    latest = _utc_datetime_from_timestamp(latest_timestamp) if latest_timestamp is not None else None

    # Treat runtime activity as real runtime output only. process.json is launcher
    # metadata and can be rewritten by recovery/status helpers long after the
    # container stopped making progress, which would incorrectly mask genuine
    # queue stalls as fresh activity.
    opencode_logs_root = opencode_home_root_for(run) / "log"
    if opencode_logs_root.exists():
        for path in opencode_logs_root.glob("*.log"):
            candidate_timestamp = _latest_process_log_activity_at(path)
            candidate = _utc_datetime_from_timestamp(candidate_timestamp) if candidate_timestamp is not None else None
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate

    return latest


def _latest_scope_file_activity_at(scope_path: Path | None) -> datetime | None:
    latest = None
    if scope_path is not None and scope_path.exists():
        for path in (
            scope_path,
            scope_path.parent / "log.md",
            scope_path.parent / "findings.md",
            scope_path.parent / "report.md",
        ):
            candidate = _path_mtime(path)
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate
    return latest


def _latest_workflow_activity_at(run: Run, scope_path: Path | None) -> datetime | None:
    latest = _latest_runtime_activity_at(run)

    scope_latest = _latest_scope_file_activity_at(scope_path)
    if scope_latest is not None and (latest is None or scope_latest > latest):
        latest = scope_latest

    latest_event = db.get_latest_non_heartbeat_event_for_run(run.id)
    event_created_at = _parse_db_timestamp(getattr(latest_event, "created_at", ""))
    if event_created_at is not None and (latest is None or event_created_at > latest):
        latest = event_created_at

    return latest


def _load_queue_state(scope_path: Path | None) -> tuple[str, int, int, int, str]:
    current_phase = "unknown"
    total_cases = 0
    pending_cases = 0
    processing_cases = 0
    queue_health = "ok"
    if scope_path is None or not scope_path.exists():
        return (current_phase, total_cases, pending_cases, processing_cases, queue_health)

    try:
        scope_payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        scope_payload = {}
    current_phase = str(scope_payload.get("current_phase") or "unknown").strip().lower().replace("-", "_")

    cases_db = scope_path.parent / "cases.db"
    if not cases_db.exists():
        return (current_phase, total_cases, pending_cases, processing_cases, queue_health)

    def _reader(connection: sqlite3.Connection) -> tuple[int, int, int]:
        total_row = connection.execute("SELECT COUNT(*) FROM cases").fetchone()
        pending_row = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'pending'"
        ).fetchone()
        processing_row = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'processing'"
        ).fetchone()
        return (
            int(total_row[0] or 0),
            int(pending_row[0] or 0),
            int(processing_row[0] or 0),
        )

    counts = _read_sqlite_with_fallback(cases_db, _reader, None)
    if counts is not None:
        total_cases, pending_cases, processing_cases = counts
        return (current_phase, total_cases, pending_cases, processing_cases, queue_health)

    try:
        with sqlite3.connect(cases_db, timeout=1.0) as connection:
            connection.execute("PRAGMA busy_timeout = 1000")
            total_cases, pending_cases, processing_cases = _reader(connection)
    except sqlite3.Error as exc:
        queue_health = "corrupt" if _is_sqlite_corruption_error(exc) else "error"

    return (current_phase, total_cases, pending_cases, processing_cases, queue_health)


def _load_processing_agents(scope_path: Path | None) -> set[str]:
    if scope_path is None or not scope_path.exists():
        return set()
    cases_db = scope_path.parent / "cases.db"
    if not cases_db.exists():
        return set()

    def _reader(connection: sqlite3.Connection) -> list[str]:
        rows = connection.execute(
            "SELECT DISTINCT assigned_agent FROM cases WHERE status = 'processing' AND assigned_agent IS NOT NULL AND TRIM(assigned_agent) != ''"
        ).fetchall()
        return [str(row[0]) for row in rows if row and row[0]]

    raw_agents = _read_sqlite_with_fallback(cases_db, _reader, [])
    return {agent for agent in raw_agents if agent}


def _format_db_timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _is_future_timestamp_skewed(timestamp: datetime | None) -> bool:
    if timestamp is None:
        return False
    return timestamp - _utc_now_naive() > timedelta(minutes=5)


def _sync_run_updated_at_from_activity(run: Run, *candidates: datetime | None) -> Run:
    latest_candidate = max((candidate for candidate in candidates if candidate is not None), default=None)
    if latest_candidate is None:
        return run

    current_updated_at = _parse_db_timestamp(run.updated_at) or _parse_db_timestamp(run.created_at)
    if _is_future_timestamp_skewed(current_updated_at):
        current_updated_at = None
    latest_candidate = latest_candidate.replace(microsecond=0)
    if current_updated_at is not None and latest_candidate <= current_updated_at:
        return run

    return db.set_run_updated_at(run.id, _format_db_timestamp(latest_candidate))


def _reattach_live_runtime_supervisor(
    run: Run,
    *,
    project: Project | None,
    user: User | None,
    runtime_pid: int | None,
) -> None:
    if project is None or user is None:
        return
    if run.status != "running":
        return
    if runtime_pid in {None, RUNTIME_PID_LOOKUP_UNAVAILABLE}:
        return
    _start_container_supervisor(run, project, user)


def _reconcile_run_status(run: Run, project: Project | None = None, user: User | None = None) -> Run:
    # User-initiated stops must never be overwritten by reconciliation logic.
    if run.status == "stopped":
        return run
    normalize_active_scope(run)
    pid = locate_runtime_pid(run)
    completion_ok, completion_reason = engagement_completion_state(run)
    if pid == RUNTIME_PID_LOOKUP_UNAVAILABLE and not completion_ok:
        return run
    if completion_ok:
        completed = run if run.status == "completed" else db.update_run_status(run.id, "completed")
        _write_run_terminal_reason(
            completed,
            reason_code="completed",
            reason_text="Run completed successfully.",
        )
        if pid not in {None, RUNTIME_PID_LOOKUP_UNAVAILABLE}:
            stop_run_runtime(completed)
        return completed

    if pid is not None:
        scope_path = _active_scope_path(run)
        current_phase, total_cases, pending_cases, processing_cases, queue_health = _load_queue_state(scope_path)
        if queue_health == "corrupt":
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="cases_db_corrupt",
                reason_text="cases.db became unreadable/corrupted while the run was active; queue state could not be trusted.",
            )
            stop_run_runtime(failed)
            return failed
        workflow_activity_at = _latest_workflow_activity_at(run, scope_path)
        if workflow_activity_at is not None:
            workflow_age = _utc_now_naive() - workflow_activity_at
            if (
                current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
                and processing_cases > 0
                and workflow_age >= timedelta(seconds=RUN_STALL_TIMEOUT_SECONDS)
            ):
                failed = db.update_run_status(run.id, "failed")
                _write_run_terminal_reason(
                    failed,
                    reason_code="queue_stalled",
                    reason_text=(
                        "Workflow produced no new process/log progress before stall timeout elapsed "
                        "while queue items remained in processing."
                    ),
                )
                stop_run_runtime(failed)
                return failed

            if (
                current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
                and pending_cases > 0
                and processing_cases == 0
                and workflow_age >= timedelta(seconds=RUN_STALL_TIMEOUT_SECONDS)
            ):
                failed = db.update_run_status(run.id, "failed")
                _write_run_terminal_reason(
                    failed,
                    reason_code="queue_stalled",
                    reason_text=(
                        "Workflow produced no new dispatch/log progress before stall timeout elapsed "
                        "while pending queue items remained undispatched."
                    ),
                )
                stop_run_runtime(failed)
                return failed

        active_runtime_agents = _active_runtime_agents(run)
        auto_resume_guard_active = _auto_resume_stall_guard_active(run)
        processing_agents = _load_processing_agents(scope_path)
        opencode_logs_root = opencode_home_root_for(run) / "log"
        permission_log_paths = [process_log_path_for(run)]
        if opencode_logs_root.exists():
            permission_log_paths.extend(sorted(opencode_logs_root.glob("*.log")))
        latest_permission_request_at = _latest_unresolved_permission_request_at(*permission_log_paths)
        orphaned_fetch = _latest_undispatched_batch_fetch(
            process_log_path_for(run),
            opencode_logs_root=opencode_logs_root,
        )
        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and latest_permission_request_at is not None
            and (_utc_now_naive() - _utc_datetime_from_timestamp(latest_permission_request_at))
            >= timedelta(seconds=PERMISSION_REQUEST_GRACE_SECONDS)
        ):
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text=(
                    "Autonomous runtime requested interactive permission approval and never resolved it; "
                    "unattended runs must stay within workspace-local inputs or fail fast instead of waiting forever."
                ),
            )
            stop_run_runtime(failed)
            return failed

        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and pending_cases > 0
            and processing_cases == 0
            and not active_runtime_agents
            and not auto_resume_guard_active
            and workflow_activity_at is not None
            and (_utc_now_naive() - workflow_activity_at) >= timedelta(seconds=PENDING_QUEUE_DISPATCH_GRACE_SECONDS)
        ):
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text="Pending queue items remained undispatched with no active runtime agent after dispatch grace period elapsed.",
            )
            stop_run_runtime(failed)
            return failed

        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and orphaned_fetch is not None
            and str(orphaned_fetch.get("agent") or "") in processing_agents
            and str(orphaned_fetch.get("agent") or "") not in active_runtime_agents
            and not auto_resume_guard_active
            and (_utc_now_naive() - _utc_datetime_from_timestamp(float(orphaned_fetch.get("timestamp") or 0.0)))
            >= timedelta(seconds=PROCESSING_AGENT_MISMATCH_GRACE_SECONDS)
        ):
            batch_type = str(orphaned_fetch.get("batch_type") or "queue")
            agent_name = str(orphaned_fetch.get("agent") or "agent")
            batch_ids = str(orphaned_fetch.get("batch_ids") or "").strip()
            reason_text = f"Fetched non-empty {batch_type} batch for {agent_name}"
            if batch_ids:
                reason_text += f" (ids: {batch_ids})"
            reason_text += " but no matching task dispatch followed before stall grace period elapsed."
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text=reason_text,
            )
            stop_run_runtime(failed)
            return failed

        orphan_activity_at = _latest_scope_file_activity_at(scope_path)
        metadata_activity_at = _latest_runtime_metadata_activity_at(run)
        metadata_activity = (
            _utc_datetime_from_timestamp(metadata_activity_at) if metadata_activity_at is not None else None
        )
        if metadata_activity is not None and (
            orphan_activity_at is None or metadata_activity > orphan_activity_at
        ):
            orphan_activity_at = metadata_activity
        has_current_task = _run_metadata_has_current_task(run)
        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and total_cases > 0
            and pending_cases == 0
            and processing_cases == 0
            and not active_runtime_agents
            and not has_current_task
            and orphan_activity_at is not None
            and (_utc_now_naive() - orphan_activity_at) >= timedelta(seconds=RUN_STALL_TIMEOUT_SECONDS)
        ):
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text=(
                    f"Run remained in {current_phase.replace('_', '-')} with no active runtime agent, "
                    "current task, or queued work before stall timeout elapsed."
                ),
            )
            stop_run_runtime(failed)
            return failed

        last_activity_at = _latest_runtime_activity_at(run)
        stale_processing_agents = _stale_processing_agents(_active_engagement_dir(run), active_runtime_agents)
        stale_processing_activity_at = last_activity_at
        if workflow_activity_at is not None and (
            stale_processing_activity_at is None or workflow_activity_at > stale_processing_activity_at
        ):
            stale_processing_activity_at = workflow_activity_at
        if metadata_activity is not None and (
            stale_processing_activity_at is None or metadata_activity > stale_processing_activity_at
        ):
            stale_processing_activity_at = metadata_activity
        recent_processing_handoff = (
            not active_runtime_agents
            and (
                auto_resume_guard_active
                or (
                    stale_processing_activity_at is not None
                    and (_utc_now_naive() - stale_processing_activity_at)
                    < timedelta(seconds=PROCESSING_AGENT_MISMATCH_GRACE_SECONDS)
                )
            )
        )
        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and stale_processing_agents
            and not recent_processing_handoff
        ):
            assigned = ", ".join(sorted(stale_processing_agents))
            if active_runtime_agents:
                active = ", ".join(sorted(active_runtime_agents))
                reason_text = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    f"after stall grace period elapsed (active agents: {active})."
                )
            else:
                reason_text = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    "after stall grace period elapsed."
                )
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text=reason_text,
            )
            stop_run_runtime(failed)
            return failed

        mismatch_activity_at = last_activity_at
        if workflow_activity_at is not None and (
            mismatch_activity_at is None or workflow_activity_at > mismatch_activity_at
        ):
            mismatch_activity_at = workflow_activity_at
        if (
            current_phase.replace("_", "-") not in EARLY_PHASE_STALL_PHASES
            and processing_agents
            and mismatch_activity_at is not None
            and (_utc_now_naive() - mismatch_activity_at) >= timedelta(seconds=PROCESSING_AGENT_MISMATCH_GRACE_SECONDS)
            and processing_agents.isdisjoint(active_runtime_agents)
        ):
            assigned = ", ".join(sorted(processing_agents))
            if active_runtime_agents:
                active = ", ".join(sorted(active_runtime_agents))
                reason_text = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    f"after stall grace period elapsed (active agents: {active})."
                )
            else:
                reason_text = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    "after stall grace period elapsed."
                )
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="queue_stalled",
                reason_text=reason_text,
            )
            stop_run_runtime(failed)
            return failed

        if last_activity_at is not None:
            log_age = _utc_now_naive() - last_activity_at
            if log_age >= timedelta(seconds=RUN_STALL_TIMEOUT_SECONDS):
                failed = db.update_run_status(run.id, "failed")
                _write_run_terminal_reason(
                    failed,
                    reason_code="queue_stalled",
                    reason_text="Runtime produced no new output before stall timeout elapsed.",
                )
                stop_run_runtime(failed)
                return failed

        early_phase_activity_at = last_activity_at
        if workflow_activity_at is not None and (
            early_phase_activity_at is None or workflow_activity_at > early_phase_activity_at
        ):
            early_phase_activity_at = workflow_activity_at

        if (
            current_phase.replace("_", "-") in EARLY_PHASE_STALL_PHASES
            and total_cases == 0
            and early_phase_activity_at is not None
            and (_utc_now_naive() - early_phase_activity_at) >= timedelta(seconds=EARLY_PHASE_STALL_TIMEOUT_SECONDS)
        ):
            failed = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(
                failed,
                reason_code="recon_stalled",
                reason_text="Runtime stalled in early recon/collect without producing any observed paths.",
            )
            stop_run_runtime(failed)
            return failed
        if run.status == "running":
            run = _sync_run_updated_at_from_activity(run, workflow_activity_at, last_activity_at)
        if run.status != "running":
            refreshed = db.update_run_status(run.id, "running")
            _clear_run_terminal_reason(refreshed)
            _reattach_live_runtime_supervisor(refreshed, project=project, user=user, runtime_pid=pid)
            if project is not None and user is not None:
                from .run_summary import refresh_run_metadata_projection

                refresh_run_metadata_projection(refreshed, project, user)
            return refreshed
        _clear_run_terminal_reason(run)
        _reattach_live_runtime_supervisor(run, project=project, user=user, runtime_pid=pid)
        if project is not None and user is not None:
            from .run_summary import refresh_run_metadata_projection

            refresh_run_metadata_projection(run, project, user)
        return run

    if run.status == "completed":
        failed = db.update_run_status(run.id, "failed")
        _write_run_terminal_reason(
            failed,
            reason_code="incomplete_terminal_state",
            reason_text=completion_reason,
        )
        stop_run_runtime(failed)
        return failed

    # New runs can briefly lack visible runtime metadata while the container and
    # docker client process are still bootstrapping. Do not immediately mark
    # them failed during that startup window.
    updated_at = _parse_db_timestamp(run.updated_at) or _parse_db_timestamp(run.created_at)
    if updated_at is not None and _utc_now_naive() - updated_at < timedelta(seconds=RUN_STARTUP_GRACE_SECONDS):
        return run

    if run.status == "running":
        engagement_dir = _active_engagement_dir(run)
        continuous_report_hold = (
            engagement_dir is not None and _continuous_observation_report_hold_active(run, engagement_dir=engagement_dir)
        )
        logged_reason_code = ""
        logged_reason_text = ""
        if engagement_dir is not None and not continuous_report_hold:
            logged_reason_code, logged_reason_text = _last_logged_stop_metadata(engagement_dir / "log.md")

        if continuous_report_hold:
            reason_code = "runtime_disappeared"
            reason_text = "continuous observation hold detached"
        else:
            reason_code = logged_reason_code or "runtime_disappeared"
            reason_text = logged_reason_text or "Runtime supervisor disappeared before the engagement reached a terminal state."
        if project is not None and user is not None:
            scope_path = _active_scope_path(run)
            current_phase, _, _, _, _ = _load_queue_state(scope_path)
            phase = current_phase.replace("_", "-") if current_phase else "unknown"
            if _maybe_auto_resume_run(
                project,
                run,
                user,
                phase=phase,
                reason_code=reason_code,
                reason_text=reason_text,
            ):
                resumed = db.get_run_by_id(run.id)
                return resumed if resumed is not None else run

        failed = db.update_run_status(run.id, "failed")
        _write_run_terminal_reason(
            failed,
            reason_code=reason_code,
            reason_text=reason_text,
        )
        stop_run_runtime(failed)
        return failed
    return run


def recover_active_run_supervisors_on_startup() -> None:
    for run in db.list_runs_by_status("running"):
        project = db.get_project_by_id(run.project_id)
        if project is None:
            continue
        user = db.get_user_by_id(project.user_id)
        if user is None:
            continue

        reconciled = _reconcile_run_status(run, project=project, user=user)
        if reconciled.status != "running":
            continue

        runtime_pid = locate_runtime_pid(reconciled)
        _reattach_live_runtime_supervisor(reconciled, project=project, user=user, runtime_pid=runtime_pid)


def list_runs_for_project(project_id: int, user: User) -> list[Run]:
    project = _project_or_404(project_id, user)
    return [_reconcile_run_status(run, project=project, user=user) for run in db.list_runs_for_project(project.id)]


def update_run_status(project_id: int, run_id: int, user: User, status_value: str) -> Run:
    project = _project_or_404(project_id, user)
    if status_value not in ALLOWED_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid run status")

    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    updated = db.update_run_status(run_id, status_value)
    if status_value == "stopped" and run.status == "running":
        _write_run_terminal_reason(
            updated,
            reason_code="user_stopped",
            reason_text="Run stopped by operator.",
        )
        stop_run_runtime(updated)
    return updated


def delete_run_for_project(project_id: int, run_id: int, user: User) -> None:
    project = _project_or_404(project_id, user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    stop_run_runtime(run)
    run_root = Path(run.engagement_root)
    if run_root.exists():
        shutil.rmtree(run_root, ignore_errors=True)
    db.delete_run(run.id)
