from __future__ import annotations

import re
import shutil
import json
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


def normalize_provider_id(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_json_object(value: str | None, field_name: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} must be a JSON object")
    return json.dumps(payload, sort_keys=True)


def create_project_for_user(
    user: User,
    name: str,
    *,
    provider_id: str = "",
    model_id: str = "",
    small_model_id: str = "",
    api_key: str = "",
    base_url: str = "",
    auth_json: str = "",
    env_json: str = "",
) -> Project:
    slug = slugify_project_name(name)
    root_path = project_root_for(user, slug)
    if db.get_project_by_user_and_slug(user.id, slug) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project already exists")

    root_path.mkdir(parents=True, exist_ok=True)
    return db.create_project(
        user.id,
        name.strip(),
        slug,
        str(root_path),
        provider_id=normalize_provider_id(provider_id),
        model_id=model_id.strip(),
        small_model_id=small_model_id.strip(),
        api_key=api_key.strip(),
        base_url=base_url.strip(),
        auth_json=normalize_json_object(auth_json, "auth_json"),
        env_json=normalize_json_object(env_json, "env_json"),
    )


def list_projects_for_user(user: User) -> list[Project]:
    return db.list_projects_for_user(user.id)


def update_project_config_for_user(
    user: User,
    project_id: int,
    *,
    provider_id: str,
    model_id: str,
    small_model_id: str,
    api_key: str | None = None,
    clear_api_key: bool = False,
    base_url: str,
    auth_json: str | None = None,
    clear_auth_json: bool = False,
    env_json: str | None = None,
    clear_env_json: bool = False,
) -> Project:
    project = db.get_project_by_id(project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    next_api_key = project.api_key
    next_auth_json = project.auth_json
    next_env_json = project.env_json
    if clear_api_key:
        next_api_key = ""
    elif api_key is not None and api_key.strip():
        next_api_key = api_key.strip()

    if clear_auth_json:
        next_auth_json = ""
    elif auth_json is not None and auth_json.strip():
        next_auth_json = normalize_json_object(auth_json, "auth_json")

    if clear_env_json:
        next_env_json = ""
    elif env_json is not None and env_json.strip():
        next_env_json = normalize_json_object(env_json, "env_json")

    return db.update_project_config(
        project.id,
        provider_id=normalize_provider_id(provider_id),
        model_id=model_id.strip(),
        small_model_id=small_model_id.strip(),
        api_key=next_api_key,
        base_url=base_url.strip(),
        auth_json=next_auth_json,
        env_json=next_env_json,
    )


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
