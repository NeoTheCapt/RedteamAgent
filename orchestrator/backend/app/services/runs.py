from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.run import Run
from ..models.user import User
from .launcher import prepare_run_runtime, start_run_runtime

ALLOWED_STATUSES = {"queued", "running", "completed", "failed"}


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


def list_runs_for_project(project_id: int, user: User) -> list[Run]:
    project = _project_or_404(project_id, user)
    return db.list_runs_for_project(project.id)


def update_run_status(project_id: int, run_id: int, user: User, status_value: str) -> Run:
    project = _project_or_404(project_id, user)
    if status_value not in ALLOWED_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid run status")

    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    return db.update_run_status(run_id, status_value)
