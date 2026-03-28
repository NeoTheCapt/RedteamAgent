from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..models.run import Run
from ..security import CurrentUser
from ..services.runs import create_run_for_project, delete_run_for_project, list_runs_for_project, update_run_status
from ..services.run_summary import list_observed_paths, summarize_run
from ..ws import broadcaster

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


class RunSummaryTargetResponse(BaseModel):
    target: str
    hostname: str
    scheme: str
    path: str
    port: int
    scope_entries: list[str]
    engagement_dir: str
    started_at: str
    status: str


class RunSummaryOverviewResponse(BaseModel):
    findings_count: int
    active_agents: int
    available_agents: int
    current_phase: str
    updated_at: str


class RunSummaryRuntimeModelResponse(BaseModel):
    configured_provider: str
    configured_model: str
    configured_small_model: str
    observed_provider: str
    observed_model: str
    status: str
    summary: str


class RunSummaryCoverageTypeResponse(BaseModel):
    type: str
    total: int | None = None
    done: int | None = None
    pending: int | None = None
    processing: int | None = None
    error: int | None = None
    count: int | None = None


class RunSummaryCurrentResponse(BaseModel):
    phase: str
    task_name: str
    agent_name: str
    summary: str


class RunSummaryPhaseResponse(BaseModel):
    phase: str
    label: str
    state: str
    task_events: int
    active_agents: int
    latest_summary: str


class RunSummaryAgentResponse(BaseModel):
    agent_name: str
    phase: str
    status: str
    task_name: str
    summary: str
    updated_at: str


class RunSummaryCoverageResponse(BaseModel):
    total_cases: int
    completed_cases: int
    pending_cases: int
    processing_cases: int
    error_cases: int
    case_types: list[RunSummaryCoverageTypeResponse]
    total_surfaces: int
    remaining_surfaces: int
    high_risk_remaining: int
    surface_statuses: dict[str, int]
    surface_types: list[RunSummaryCoverageTypeResponse]


class RunSummaryResponse(BaseModel):
    target: RunSummaryTargetResponse
    overview: RunSummaryOverviewResponse
    runtime_model: RunSummaryRuntimeModelResponse
    coverage: RunSummaryCoverageResponse
    current: RunSummaryCurrentResponse
    phases: list[RunSummaryPhaseResponse]
    agents: list[RunSummaryAgentResponse]


class ObservedPathResponse(BaseModel):
    method: str
    url: str
    type: str
    status: str
    assigned_agent: str
    source: str


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


@router.get("/{run_id}/summary", response_model=RunSummaryResponse)
def get_run_summary(project_id: int, run_id: int, current_user: CurrentUser) -> RunSummaryResponse:
    summary = summarize_run(project_id, run_id, current_user)
    return RunSummaryResponse(
        target=RunSummaryTargetResponse(**summary.target),
        overview=RunSummaryOverviewResponse(**summary.overview),
        runtime_model=RunSummaryRuntimeModelResponse(**summary.runtime_model),
        coverage=RunSummaryCoverageResponse(**summary.coverage),
        current=RunSummaryCurrentResponse(**summary.current),
        phases=[RunSummaryPhaseResponse(**item) for item in summary.phases],
        agents=[RunSummaryAgentResponse(**item) for item in summary.agents],
    )


@router.get("/{run_id}/observed-paths", response_model=list[ObservedPathResponse])
def get_observed_paths(project_id: int, run_id: int, current_user: CurrentUser) -> list[ObservedPathResponse]:
    items = list_observed_paths(project_id, run_id, current_user)
    return [ObservedPathResponse(**asdict(item)) for item in items]


@router.post("/{run_id}/status", response_model=RunResponse)
async def set_run_status(
    project_id: int,
    run_id: int,
    request: UpdateRunStatusRequest,
    current_user: CurrentUser,
) -> RunResponse:
    run = update_run_status(project_id, run_id, current_user, request.status)
    response = _run_response(run)
    await broadcaster.publish(
        project_id,
        run_id,
        {
            "type": "run.status.updated",
            "project_id": project_id,
            "run_id": run_id,
            "run": response.model_dump(),
        },
    )
    return response


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(project_id: int, run_id: int, current_user: CurrentUser) -> None:
    delete_run_for_project(project_id, run_id, current_user)
