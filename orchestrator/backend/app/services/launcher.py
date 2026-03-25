from __future__ import annotations

import json
import os
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

    subprocess.run(
        [str(settings.install_script_path), "opencode", str(workspace_root)],
        cwd=str(settings.install_script_path.parent),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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


def _watch_process(run: Run, process: subprocess.Popen[bytes], log_handle) -> None:
    return_code = process.wait()
    log_handle.close()
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
        log_handle.write(f"launcher failed: {exc}\n".encode("utf-8"))
        log_handle.close()
        return db.update_run_status(run.id, "failed")

    running = db.update_run_status(run.id, "running")
    Thread(target=_watch_process, args=(running, process, log_handle), daemon=True).start()
    return running
