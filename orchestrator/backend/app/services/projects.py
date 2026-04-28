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


_ENV_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# Reserved at the API boundary — orchestrator owns these and silently
# overwriting them via env_json would break run wiring.
_RESERVED_ENV_KEYS = frozenset({
    "ORCHESTRATOR_BASE_URL",
    "ORCHESTRATOR_TOKEN",
    "ORCHESTRATOR_PROJECT_ID",
    "ORCHESTRATOR_RUN_ID",
    "OPENCODE_HOME",
})


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _parse_json_object(raw: str, field_name: str, example: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _bad_request(f"{field_name} must be valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise _bad_request(f"{field_name} must be a JSON object, e.g. {example}")
    return payload


def _validate_string_dict(value: object, field_path: str) -> None:
    if not isinstance(value, dict):
        raise _bad_request(f"{field_path} must be a JSON object of string values, got {type(value).__name__}")
    for k, v in value.items():
        if not isinstance(k, str):
            raise _bad_request(f"{field_path}: keys must be strings")
        if not isinstance(v, str):
            raise _bad_request(f"{field_path}.{k} must be a string, got {type(v).__name__}")


def validate_auth_json(value: str | None) -> str:
    """Validate auth_json shape and return canonical JSON.

    Schema (every top-level key is optional):
      {
        "cookies": Record<string,string>,
        "headers": Record<string,string>,
        "tokens":  Record<string,string>,
        "discovered_credentials": list,
        "validated_credentials":  list,
        "credentials":            list,   // legacy compat
      }
    Extra top-level keys are passed through unchanged so future agent-side
    additions don't have to be re-allowlisted here.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    payload = _parse_json_object(
        raw,
        "auth_json",
        '{"cookies":{},"headers":{"Authorization":"Bearer ..."},"tokens":{}}',
    )
    for key in ("cookies", "headers", "tokens"):
        if key in payload:
            _validate_string_dict(payload[key], f"auth_json.{key}")
    for key in ("discovered_credentials", "validated_credentials", "credentials"):
        if key in payload and not isinstance(payload[key], list):
            raise _bad_request(
                f"auth_json.{key} must be a JSON array, got {type(payload[key]).__name__}"
            )
    return json.dumps(payload, sort_keys=True)


def validate_env_json(value: str | None) -> str:
    """Validate env_json — POSIX env-var keys, scalar values.

    Keys must match `[A-Z_][A-Z0-9_]*`. Values must be string / number / bool
    (coerced to string when injected into the container at run time).
    Reserved orchestrator keys (ORCHESTRATOR_*, OPENCODE_HOME) are rejected
    so users cannot accidentally clobber the run wiring.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    payload = _parse_json_object(
        raw,
        "env_json",
        '{"HTTP_PROXY":"http://proxy:8080","MY_TARGET_USER":"alice"}',
    )
    for key, val in payload.items():
        if not isinstance(key, str) or not _ENV_KEY_PATTERN.match(key):
            raise _bad_request(
                f"env_json key {key!r} must match [A-Z_][A-Z0-9_]* (POSIX env-var convention)"
            )
        if key in _RESERVED_ENV_KEYS:
            raise _bad_request(
                f"env_json key {key!r} is reserved by the orchestrator and cannot be overridden"
            )
        if not isinstance(val, (str, int, float, bool)) or isinstance(val, type(None)):
            raise _bad_request(
                f"env_json.{key} must be a string, number, or boolean, got {type(val).__name__}"
            )
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
    crawler_json: str = "{}",
    parallel_json: str = "{}",
    agents_json: str = "{}",
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
        auth_json=validate_auth_json(auth_json),
        env_json=validate_env_json(env_json),
        crawler_json=normalize_json_object(crawler_json, "crawler_json") or "{}",
        parallel_json=normalize_json_object(parallel_json, "parallel_json") or "{}",
        agents_json=normalize_json_object(agents_json, "agents_json") or "{}",
    )


def list_projects_for_user(user: User) -> list[Project]:
    return db.list_projects_for_user(user.id)


def get_project_for_user(user: User, project_id: int) -> Project:
    project = db.get_project_by_id(project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


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
        next_auth_json = validate_auth_json(auth_json)

    if clear_env_json:
        next_env_json = ""
    elif env_json is not None and env_json.strip():
        next_env_json = validate_env_json(env_json)

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


def update_project_for_user(user: User, project_id: int, **fields: str) -> Project:
    """Partial-update a project — only the supplied fields are changed.

    Validates JSON fields and, if *name* is changed, regenerates the slug
    and checks for collisions.  An empty *fields* dict is a no-op that
    returns the current project state.
    """
    project = db.get_project_by_id(project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if not fields:
        return project

    # Validate JSON fields. auth_json and env_json get full schema checks
    # (cookies/headers/tokens shape, env-var key pattern, reserved-key reject);
    # the structured-editor fields (crawler/parallel/agents) just need to parse
    # as a JSON object since their keys are emitted by purpose-built editors.
    if "auth_json" in fields and fields["auth_json"]:
        fields = dict(fields)
        fields["auth_json"] = validate_auth_json(fields["auth_json"])
    if "env_json" in fields and fields["env_json"]:
        fields = dict(fields)
        fields["env_json"] = validate_env_json(fields["env_json"])
    for json_field in ("crawler_json", "parallel_json", "agents_json"):
        if json_field in fields and fields[json_field]:
            try:
                payload = json.loads(fields[json_field])
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{json_field} must be valid JSON: {exc}",
                ) from exc
            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{json_field} must be a JSON object",
                )

    # If name is being changed, regenerate slug and check for collision
    if "name" in fields and fields["name"].strip():
        new_name = fields["name"].strip()
        new_slug = slugify_project_name(new_name)
        fields = dict(fields)
        fields["name"] = new_name
        if new_slug != project.slug:
            collision = db.get_project_by_user_and_slug(user.id, new_slug)
            if collision is not None and collision.id != project.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another project already uses this name",
                )
            fields["slug"] = new_slug

    return db.update_project(project_id, **fields)


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
