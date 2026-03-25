from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..models.project import Project
from ..models.run import Run


def runtime_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "runtime"


def workspace_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "workspace"


def opencode_home_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "opencode-home"


def metadata_path_for(run: Run) -> Path:
    return Path(run.engagement_root) / "run.json"


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
    }
    metadata_path_for(run).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
