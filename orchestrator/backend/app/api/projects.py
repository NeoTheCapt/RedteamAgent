from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..models.project import Project
from ..security import CurrentUser
from ..services.projects import (
    create_project_for_user,
    delete_project_for_user,
    list_projects_for_user,
    update_project_config_for_user,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider_id: str = Field(default="", max_length=64)
    model_id: str = Field(default="", max_length=256)
    small_model_id: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=1024)
    base_url: str = Field(default="", max_length=512)
    auth_json: str = Field(default="", max_length=20000)
    env_json: str = Field(default="", max_length=20000)


class UpdateProjectConfigRequest(BaseModel):
    provider_id: str = Field(default="", max_length=64)
    model_id: str = Field(default="", max_length=256)
    small_model_id: str = Field(default="", max_length=256)
    api_key: str | None = Field(default=None, max_length=1024)
    clear_api_key: bool = False
    base_url: str = Field(default="", max_length=512)
    auth_json: str | None = Field(default=None, max_length=20000)
    clear_auth_json: bool = False
    env_json: str | None = Field(default=None, max_length=20000)
    clear_env_json: bool = False


class ProjectResponse(BaseModel):
    id: int
    name: str
    slug: str
    root_path: str
    provider_id: str
    model_id: str
    small_model_id: str
    base_url: str
    api_key_configured: bool
    auth_configured: bool
    env_configured: bool


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=project.slug,
        root_path=project.root_path,
        provider_id=project.provider_id,
        model_id=project.model_id,
        small_model_id=project.small_model_id,
        base_url=project.base_url,
        api_key_configured=bool(project.api_key),
        auth_configured=bool(project.auth_json),
        env_configured=bool(project.env_json),
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: CreateProjectRequest, current_user: CurrentUser) -> ProjectResponse:
    project = create_project_for_user(
        current_user,
        request.name,
        provider_id=request.provider_id,
        model_id=request.model_id,
        small_model_id=request.small_model_id,
        api_key=request.api_key,
        base_url=request.base_url,
        auth_json=request.auth_json,
        env_json=request.env_json,
    )
    return _project_response(project)


@router.get("", response_model=list[ProjectResponse])
def list_projects(current_user: CurrentUser) -> list[ProjectResponse]:
    return [_project_response(project) for project in list_projects_for_user(current_user)]


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project_config(
    project_id: int,
    request: UpdateProjectConfigRequest,
    current_user: CurrentUser,
) -> ProjectResponse:
    project = update_project_config_for_user(
        current_user,
        project_id,
        provider_id=request.provider_id,
        model_id=request.model_id,
        small_model_id=request.small_model_id,
        api_key=request.api_key,
        clear_api_key=request.clear_api_key,
        base_url=request.base_url,
        auth_json=request.auth_json,
        clear_auth_json=request.clear_auth_json,
        env_json=request.env_json,
        clear_env_json=request.clear_env_json,
    )
    return _project_response(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, current_user: CurrentUser) -> None:
    delete_project_for_user(current_user, project_id)
