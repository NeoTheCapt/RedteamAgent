from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import HTTPException, status

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.user import User

SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify_project_name(name: str) -> str:
    normalized = name.strip().lower()
    slug = SLUG_PATTERN.sub("-", normalized).strip("-")
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project name must contain letters or digits")
    return slug


def project_root_for(user: User, slug: str) -> Path:
    return settings.projects_dir / user.username / slug


def create_project_for_user(user: User, name: str) -> Project:
    slug = slugify_project_name(name)
    root_path = project_root_for(user, slug)
    if db.get_project_by_user_and_slug(user.id, slug) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project already exists")

    root_path.mkdir(parents=True, exist_ok=True)
    return db.create_project(user.id, name.strip(), slug, str(root_path))


def list_projects_for_user(user: User) -> list[Project]:
    return db.list_projects_for_user(user.id)


def delete_project_for_user(user: User, project_id: int) -> None:
    project = db.get_project_by_id(project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    from .runs import delete_run_for_project

    for run in db.list_runs_for_project(project.id):
        delete_run_for_project(project.id, run.id, user)

    root_path = Path(project.root_path)
    if root_path.exists():
        shutil.rmtree(root_path, ignore_errors=True)
    db.delete_project(project.id)
