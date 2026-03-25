from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..models.project import Project
from ..security import CurrentUser
from ..services.projects import create_project_for_user, delete_project_for_user, list_projects_for_user

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ProjectResponse(BaseModel):
    id: int
    name: str
    slug: str
    root_path: str


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=project.slug,
        root_path=project.root_path,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: CreateProjectRequest, current_user: CurrentUser) -> ProjectResponse:
    project = create_project_for_user(current_user, request.name)
    return _project_response(project)


@router.get("", response_model=list[ProjectResponse])
def list_projects(current_user: CurrentUser) -> list[ProjectResponse]:
    return [_project_response(project) for project in list_projects_for_user(current_user)]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, current_user: CurrentUser) -> None:
    delete_project_for_user(current_user, project_id)
