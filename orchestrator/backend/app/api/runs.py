from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..models.run import Run
from ..security import CurrentUser
from ..services.runs import create_run_for_project, list_runs_for_project, update_run_status

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    target: str = Field(min_length=1, max_length=512)


class UpdateRunStatusRequest(BaseModel):
    status: str


class RunResponse(BaseModel):
    id: int
    target: str
    status: str
    engagement_root: str


def _run_response(run: Run) -> RunResponse:
    return RunResponse(
        id=run.id,
        target=run.target,
        status=run.status,
        engagement_root=run.engagement_root,
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(project_id: int, request: CreateRunRequest, current_user: CurrentUser) -> RunResponse:
    run = create_run_for_project(project_id, current_user, request.target)
    return _run_response(run)


@router.get("", response_model=list[RunResponse])
def list_runs(project_id: int, current_user: CurrentUser) -> list[RunResponse]:
    return [_run_response(run) for run in list_runs_for_project(project_id, current_user)]


@router.post("/{run_id}/status", response_model=RunResponse)
def set_run_status(
    project_id: int,
    run_id: int,
    request: UpdateRunStatusRequest,
    current_user: CurrentUser,
) -> RunResponse:
    run = update_run_status(project_id, run_id, current_user, request.status)
    return _run_response(run)
