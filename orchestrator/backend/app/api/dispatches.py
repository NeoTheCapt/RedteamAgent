from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.runs import _project_or_404

router = APIRouter(
    prefix="/projects/{project_id}/runs/{run_id}/dispatches",
    tags=["dispatches"],
)


def _serialize(d) -> dict:
    return {
        "id": d.id,
        "phase": d.phase,
        "round": d.round,
        "agent": d.agent,
        "slot": d.slot,
        "task": d.task,
        "state": d.state,
        "started_at": d.started_at,
        "finished_at": d.finished_at,
        "error": d.error,
    }


@router.get("")
def list_dispatches(
    project_id: int,
    run_id: int,
    current_user: CurrentUser,
    phase: str | None = None,
) -> list[dict]:
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return [_serialize(d) for d in db.list_dispatches(run.id, phase=phase)]
