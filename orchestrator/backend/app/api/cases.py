from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.runs import _project_or_404

router = APIRouter(
    prefix="/projects/{project_id}/runs/{run_id}/cases",
    tags=["cases"],
)


def _serialize(c) -> dict:
    duration_ms = None
    if c.started_at is not None and c.finished_at is not None:
        duration_ms = (c.finished_at - c.started_at) * 1000
    return {
        "case_id": c.case_id,
        "method": c.method,
        "path": c.path,
        "category": c.category,
        "dispatch_id": c.dispatch_id,
        "state": c.state,
        "result": c.result,
        "finding_id": c.finding_id,
        "started_at": c.started_at,
        "finished_at": c.finished_at,
        "duration_ms": duration_ms,
    }


@router.get("")
def list_cases(
    project_id: int,
    run_id: int,
    current_user: CurrentUser,
    state: str | None = None,
    method: str | None = None,
    category: str | None = None,
) -> list[dict]:
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return [
        _serialize(c)
        for c in db.list_cases(run.id, state=state, method=method, category=category)
    ]


@router.get("/{case_id}")
def get_case(
    project_id: int,
    run_id: int,
    case_id: int,
    current_user: CurrentUser,
) -> dict:
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    c = db.get_case(run.id, case_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _serialize(c)
