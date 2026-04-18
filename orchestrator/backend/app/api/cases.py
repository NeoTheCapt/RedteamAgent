from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.run_summary import (
    _active_engagement_root,
    _cases_db_candidates,
    _read_sqlite_with_fallback,
    _resolve_cases_db,
)
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


def _merge_case(cases_db_row: dict, structured: dict) -> dict:
    """Per-field merge: structured wins EXCEPT for empty/null fields.

    When ``case_done`` arrives before ``dispatch_start``, ``event_apply``
    creates a structured row with ``method=''`` and ``path=''``.  A plain
    "structured wins wholesale" merge would erase the real route data
    already stored in cases.db.  This helper falls back to the cases.db
    value for any field where the structured value is None or an empty
    string.
    """
    merged = dict(cases_db_row)
    for key, value in structured.items():
        if value is None or (isinstance(value, str) and value == ""):
            continue
        merged[key] = value
    return merged


# Status mapping from the agent's cases.db status values to the structured schema states.
_AGENT_STATUS_TO_STATE: dict[str, str] = {
    "done": "done",
    "pending": "queued",
    "processing": "running",
    "error": "error",
}


def _agent_db_row_to_api(payload: dict, fallback_case_id: int) -> dict:
    """Convert a raw cases.db row dict to the API response shape.

    Prefers ``url_path`` (route-only) over ``url`` (absolute) for the
    ``path`` field, falling back to ``url`` when ``url_path`` is absent
    or empty.  This prevents the Cases tab from showing full absolute URLs
    when the agent DB schema includes a dedicated ``url_path`` column.
    """
    raw_status = str(payload.get("status") or "").strip().lower()
    state = _AGENT_STATUS_TO_STATE.get(raw_status, raw_status or "queued")
    url_path = str(payload.get("url_path") or "").strip()
    url_fallback = str(payload.get("url") or "").strip()
    path_value = url_path or url_fallback
    return {
        "case_id": int(payload.get("id") or fallback_case_id),
        "method": str(payload.get("method") or "GET").strip() or "GET",
        "path": path_value,
        "category": str(payload.get("type") or "").strip() or None,
        "dispatch_id": None,
        "state": state,
        "result": None,
        "finding_id": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
    }


def _read_case_from_agent_db(cases_db_path: Path, case_id: int) -> dict | None:
    """Read a single case row by id from the agent's cases.db.

    Mirrors ``_read_cases_from_agent_db`` but adds a WHERE id=? filter and
    returns one dict (in the API shape) or None when the row is absent.
    Uses ``_read_sqlite_with_fallback`` to handle WAL-locked databases.
    Selects ``url_path`` when present so the ``path`` field prefers the
    route-only value over the absolute URL.
    """
    def _reader(conn: sqlite3.Connection) -> tuple | None:
        col_rows = conn.execute("PRAGMA table_info(cases)").fetchall()
        col_names = {str(r[1]) for r in col_rows}
        if not col_names:
            return None
        select = [c for c in ("id", "method", "url_path", "url", "type", "status") if c in col_names]
        if not select:
            return None
        row = conn.execute(
            f"SELECT {', '.join(select)} FROM cases WHERE id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return (select, row)

    result = _read_sqlite_with_fallback(cases_db_path, _reader, None)
    if result is None:
        return None
    select, row = result
    payload = dict(zip(select, row, strict=False))
    return _agent_db_row_to_api(payload, case_id)


def _read_cases_from_agent_db(cases_db_path: Path) -> list[dict]:
    """Read case rows from the agent's cases.db and convert to the API shape.

    The agent's cases.db schema uses different column names than the structured
    cases table:  url/type/status  vs  path/category/state.  Map them across so
    the response is consistent with the normal code-path.
    Uses ``_read_sqlite_with_fallback`` to handle WAL-locked databases.
    """
    def _reader(conn: sqlite3.Connection) -> tuple[list[str], list] | None:
        col_rows = conn.execute("PRAGMA table_info(cases)").fetchall()
        col_names = {str(r[1]) for r in col_rows}
        if not col_names:
            return None
        select = [c for c in ("id", "method", "url_path", "url", "type", "status") if c in col_names]
        if not select:
            return None
        rows = conn.execute(
            f"SELECT {', '.join(select)} FROM cases ORDER BY id"
        ).fetchall()
        return (select, rows)

    result = _read_sqlite_with_fallback(cases_db_path, _reader, None)
    if result is None:
        return []
    select, rows = result

    results: list[dict] = []
    for i, row in enumerate(rows):
        payload = dict(zip(select, row, strict=False))
        results.append(_agent_db_row_to_api(payload, i + 1))
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

    # Always read from both sources and merge.
    # cases.db is authoritative for the full set of cases (agent's view of the
    # queue); the structured table carries richer metadata (started_at,
    # finished_at, duration_ms, phase) but may be PARTIAL when some
    # dispatch_start POSTs were dropped.  Merging prevents the Cases tab from
    # showing only the partial structured rows while the Dashboard summary
    # (which reads cases.db directly) shows a larger total.
    structured_list = db.list_cases(run.id, state=state, method=method, category=category)
    structured: dict[int, dict] = {c.case_id: _serialize(c) for c in structured_list}

    # Load cases.db rows (no filter — agent DB schema is different).
    cases_db_rows: list[dict] = []
    run_root = Path(run.engagement_root)
    try:
        active_root = _active_engagement_root(run_root)
        cases_db_path = _resolve_cases_db(run_root, active_root)
        cases_db_rows = _read_cases_from_agent_db(cases_db_path)
    except Exception:
        pass

    # Merge: cases.db provides the base set; structured rows overlay with richer
    # metadata.  Per-field merge: structured wins only when its value is
    # non-empty/non-null.  This handles the out-of-order case where a
    # case_done event arrives before dispatch_start, causing the structured
    # row to have blank method/path placeholders that would otherwise
    # overwrite the real route data from cases.db.
    merged: dict[int, dict] = {}
    for row in cases_db_rows:
        merged[row["case_id"]] = row
    for case_id, case in structured.items():
        if case_id in merged:
            merged[case_id] = _merge_case(merged[case_id], case)
        else:
            merged[case_id] = case

    if not merged:
        return []

    # Apply state/method/category filters to the merged result (filters were
    # already applied to structured rows by db.list_cases; apply manually to
    # cases.db-only rows here).
    result = list(merged.values())
    if state is not None:
        result = [r for r in result if r.get("state") == state]
    if method is not None:
        result = [r for r in result if (r.get("method") or "").upper() == method.upper()]
    if category is not None:
        result = [r for r in result if r.get("category") == category]

    result.sort(key=lambda r: r["case_id"])
    return result


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

    # Always attempt to read the cases.db row so we can merge it with the
    # structured row.  This handles the out-of-order case_done-before-
    # dispatch_start scenario where the structured row has blank method/path.
    run_root = Path(run.engagement_root)
    cases_db_row: dict | None = None
    try:
        active_root = _active_engagement_root(run_root)
        cases_db_path = _resolve_cases_db(run_root, active_root)
        cases_db_row = _read_case_from_agent_db(cases_db_path, case_id)
    except Exception:
        pass

    if c is not None:
        serialized = _serialize(c)
        if cases_db_row is not None:
            return _merge_case(cases_db_row, serialized)
        return serialized

    # Structured row absent — fall back to cases.db only.
    if cases_db_row is not None:
        return cases_db_row
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
