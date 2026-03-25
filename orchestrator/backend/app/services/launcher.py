from __future__ import annotations

import json
import os
import shutil
import subprocess
from threading import Thread
from pathlib import Path

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.run import Run
from ..models.user import User
from ..security import create_session_token, session_expiry_timestamp


def runtime_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "runtime"


def workspace_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "workspace"


def opencode_home_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "opencode-home"


def metadata_path_for(run: Run) -> Path:
    return Path(run.engagement_root) / "run.json"


def process_log_path_for(run: Run) -> Path:
    return runtime_root_for(run) / "process.log"


def _active_engagement_dir(run: Run) -> Path | None:
    active_file = workspace_root_for(run) / "engagements" / ".active"
    if not active_file.exists():
        return None

    active_name = active_file.read_text(encoding="utf-8").strip()
    if not active_name:
        return None

    active_dir = workspace_root_for(run) / "engagements" / active_name
    return active_dir if active_dir.exists() else None


def _heartbeat_context(run: Run) -> tuple[str, str]:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return ("unknown", "Runtime active; waiting for engagement initialization.")

    scope_path = engagement_dir / "scope.json"
    if not scope_path.exists():
        return ("unknown", "Runtime active; engagement created, waiting for phase details.")

    try:
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ("unknown", "Runtime active; scope metadata is not yet readable.")

    phase = str(scope.get("current_phase") or "unknown")
    return (phase, f"Runtime active in {phase}; waiting for new agent output.")


def prepare_run_runtime(project: Project, run: Run) -> None:
    run_root = Path(run.engagement_root)
    run_root.mkdir(parents=True, exist_ok=True)
    runtime_root_for(run).mkdir(parents=True, exist_ok=True)
    workspace_root_for(run).mkdir(parents=True, exist_ok=True)
    opencode_home_root_for(run).mkdir(parents=True, exist_ok=True)

    metadata = {
        "project_id": project.id,
        "project_slug": project.slug,
        "run_id": run.id,
        "target": run.target,
        "status": run.status,
        "engagement_root": run.engagement_root,
        "runtime_root": str(runtime_root_for(run)),
        "workspace_root": str(workspace_root_for(run)),
        "opencode_home_root": str(opencode_home_root_for(run)),
        "agent_source_dir": str(settings.agent_source_dir),
        "process_log": str(process_log_path_for(run)),
    }
    metadata_path_for(run).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _ensure_opencode_runtime_seeded(run: Run) -> None:
    workspace_root = workspace_root_for(run)
    sentinel = workspace_root / ".opencode" / "opencode.json"
    if sentinel.exists():
        return

    for relative_dir in (".opencode", "skills", "references", "scripts", "docker"):
        source_dir = settings.agent_source_dir / relative_dir
        target_dir = workspace_root / relative_dir
        if source_dir.exists():
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)

    env_template = settings.agent_source_dir / ".env.example"
    env_target = workspace_root / ".env"
    if env_template.exists() and not env_target.exists():
        shutil.copy2(env_template, env_target)

    (workspace_root / "engagements").mkdir(parents=True, exist_ok=True)


def _runtime_env(project: Project, run: Run, user: User) -> dict[str, str]:
    token = create_session_token()
    db.create_session(user.id, token, session_expiry_timestamp())
    env = os.environ.copy()
    env.update(
        {
            "OPENCODE_HOME": str(opencode_home_root_for(run)),
            "ORCHESTRATOR_BASE_URL": settings.orchestrator_public_url,
            "ORCHESTRATOR_TOKEN": token,
            "ORCHESTRATOR_PROJECT_ID": str(project.id),
            "ORCHESTRATOR_RUN_ID": str(run.id),
        }
    )
    return env


def _append_runtime_event(run: Run, event_type: str, phase: str, summary: str) -> None:
    db.create_event(run.id, event_type, phase, "runtime", "launcher", summary)


def _supervise_process(run: Run, process: subprocess.Popen[bytes], log_handle, heartbeat_interval: int = 5) -> None:
    while True:
        try:
            return_code = process.wait(timeout=heartbeat_interval)
            break
        except subprocess.TimeoutExpired:
            phase, summary = _heartbeat_context(run)
            _append_runtime_event(run, "run.heartbeat", phase, summary)

    log_handle.close()
    phase, summary = _heartbeat_context(run)
    _append_runtime_event(
        run,
        "run.completed" if return_code == 0 else "run.failed",
        phase,
        "Runtime finished successfully." if return_code == 0 else "Runtime exited with failure.",
    )
    db.update_run_status(run.id, "completed" if return_code == 0 else "failed")


def start_run_runtime(project: Project, run: Run, user: User) -> Run:
    prepare_run_runtime(project, run)
    process_log_path_for(run).parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(process_log_path_for(run), "ab")

    try:
        _ensure_opencode_runtime_seeded(run)
        process = subprocess.Popen(
            [settings.opencode_command, "run", "--format", "json", f"/autoengage {run.target}"],
            cwd=str(workspace_root_for(run)),
            env=_runtime_env(project, run, user),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        log_handle.write(f"launcher failed: {exc!r}\n".encode("utf-8"))
        log_handle.close()
        return db.update_run_status(run.id, "failed")

    running = db.update_run_status(run.id, "running")
    _append_runtime_event(running, "run.started", "unknown", "Runtime launched; waiting for agent activity.")
    Thread(target=_supervise_process, args=(running, process, log_handle), daemon=True).start()
    return running
