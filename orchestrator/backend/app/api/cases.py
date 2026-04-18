from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.run_summary import _active_engagement_root, _cases_db_candidates, _resolve_cases_db
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


# Status mapping from the agent's cases.db status values to the structured schema states.
_AGENT_STATUS_TO_STATE: dict[str, str] = {
    "done": "done",
    "pending": "queued",
    "processing": "running",
    "error": "error",
}


def _read_case_from_agent_db(cases_db_path: Path, case_id: int) -> dict | None:
    """Read a single case row by id from the agent's cases.db.

    Mirrors ``_read_cases_from_agent_db`` but adds a WHERE id=? filter and
    returns one dict (in the API shape) or None when the row is absent.
    """
    if not cases_db_path.exists():
        return None
    try:
        with sqlite3.connect(cases_db_path, timeout=1.0) as conn:
            col_rows = conn.execute("PRAGMA table_info(cases)").fetchall()
            col_names = {str(r[1]) for r in col_rows}
            if not col_names:
                return None
            select = [c for c in ("id", "method", "url", "type", "status") if c in col_names]
            if not select:
                return None
            row = conn.execute(
                f"SELECT {', '.join(select)} FROM cases WHERE id = ?",
                (case_id,),
            ).fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        return None
    payload = dict(zip(select, row, strict=False))
    raw_status = str(payload.get("status") or "").strip().lower()
    state = _AGENT_STATUS_TO_STATE.get(raw_status, raw_status or "queued")
    return {
        "case_id": int(payload.get("id") or case_id),
        "method": str(payload.get("method") or "GET").strip() or "GET",
        "path": str(payload.get("url") or "").strip(),
        "category": str(payload.get("type") or "").strip() or None,
        "dispatch_id": None,
        "state": state,
        "result": None,
        "finding_id": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
    }


def _read_cases_from_agent_db(cases_db_path: Path) -> list[dict]:
    """Read case rows from the agent's cases.db and convert to the API shape.

    The agent's cases.db schema uses different column names than the structured
    cases table:  url/type/status  vs  path/category/state.  Map them across so
    the response is consistent with the normal code-path.
    """
    if not cases_db_path.exists():
        return []
    try:
        with sqlite3.connect(cases_db_path, timeout=1.0) as conn:
            col_rows = conn.execute("PRAGMA table_info(cases)").fetchall()
            col_names = {str(r[1]) for r in col_rows}
            if not col_names:
                return []
            select = [c for c in ("id", "method", "url", "type", "status") if c in col_names]
            if not select:
                return []
            rows = conn.execute(
                f"SELECT {', '.join(select)} FROM cases ORDER BY id"
            ).fetchall()
    except sqlite3.Error:
        return []

    results: list[dict] = []
    for i, row in enumerate(rows):
        payload = dict(zip(select, row, strict=False))
        raw_status = str(payload.get("status") or "").strip().lower()
        state = _AGENT_STATUS_TO_STATE.get(raw_status, raw_status or "queued")
        results.append({
            "case_id": int(payload.get("id") or (i + 1)),
            "method": str(payload.get("method") or "GET").strip() or "GET",
            "path": str(payload.get("url") or "").strip(),
            "category": str(payload.get("type") or "").strip() or None,
            "dispatch_id": None,
            "state": state,
            "result": None,
            "finding_id": None,
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
        })
    return results


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
    structured = db.list_cases(run.id, state=state, method=method, category=category)
    if structured:
        return [_serialize(c) for c in structured]

    # Fallback: structured cases table is empty (historical run or dropped event
    # POSTs). Read from the agent's cases.db so the Cases tab is not blank when
    # the Dashboard summary already shows non-zero totals from the same file.
    # Filters are not applied to the fallback — the agent DB schema is different.
    run_root = Path(run.engagement_root)
    try:
        active_root = _active_engagement_root(run_root)
        cases_db_path = _resolve_cases_db(run_root, active_root)
    except Exception:
        return []
    return _read_cases_from_agent_db(cases_db_path)


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
        # Fall back to agent cases.db (same pattern as list_cases).
        run_root = Path(run.engagement_root)
        try:
            active_root = _active_engagement_root(run_root)
            cases_db_path = _resolve_cases_db(run_root, active_root)
        except Exception:
            cases_db_path = None
        if cases_db_path is not None:
            fallback = _read_case_from_agent_db(cases_db_path, case_id)
            if fallback is not None:
                return fallback
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _serialize(c)
