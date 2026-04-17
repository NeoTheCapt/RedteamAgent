from __future__ import annotations

import time
from typing import Any

from .. import db


_OUTCOME_TO_STATE = {
    "DONE": "done",
    "REQUEUE": "queued",
    "ERROR": "error",
}


def apply(*, run_id: int, kind: str, phase: str, payload: dict[str, Any]) -> None:
    """Inspect a typed event and perform DB side-effects.

    Called from the POST /events handler after the event row is persisted.
    Unknown or legacy kinds are no-ops.
    """
    if kind == "dispatch_start":
        _apply_dispatch_start(run_id, phase, payload)
    elif kind == "dispatch_done":
        _apply_dispatch_done(run_id, payload)
    elif kind == "case_done":
        _apply_case_done(run_id, payload)
    elif kind == "finding":
        _apply_finding(run_id, payload)
    elif kind == "phase_enter":
        _apply_phase_enter(run_id, payload, phase)
    # legacy / unknown: no-op


def _apply_dispatch_start(run_id: int, phase: str, payload: dict[str, Any]) -> None:
    batch_id = str(payload.get("batch", ""))
    if not batch_id:
        return
    round_val = int(payload.get("round", 0))
    db.upsert_dispatch(
        dispatch_id=batch_id,
        run_id=run_id,
        phase=phase or "consume",
        round=round_val,
        agent=str(payload.get("agent", "")),
        slot=str(payload.get("slot", "")),
        task=payload.get("task"),
        state="running",
        started_at=int(time.time()),
    )
    # Pre-seed case rows from the cases[] array (B2.1)
    for case in payload.get("cases") or []:
        try:
            case_id = int(case["id"])
        except (KeyError, TypeError, ValueError):
            continue
        db.upsert_case(
            case_id=case_id,
            run_id=run_id,
            method=str(case.get("method", "")),
            path=str(case.get("path", "")),
            category=case.get("type"),
            dispatch_id=batch_id,
            state="queued",
        )


def _apply_dispatch_done(run_id: int, payload: dict[str, Any]) -> None:
    batch_id = str(payload.get("batch", ""))
    if not batch_id:
        return
    existing = db.get_dispatch(run_id, batch_id)
    if existing is None:
        return
    db.upsert_dispatch(
        dispatch_id=batch_id,
        run_id=run_id,
        phase=existing.phase,
        round=existing.round,
        agent=existing.agent,
        slot=existing.slot,
        task=existing.task,
        state=str(payload.get("state", "done")),
        started_at=existing.started_at,
        finished_at=int(time.time()),
    )


def _apply_case_done(run_id: int, payload: dict[str, Any]) -> None:
    try:
        case_id = int(payload["case_id"])
    except (KeyError, TypeError, ValueError):
        return
    outcome = str(payload.get("outcome", "")).upper()
    state = _OUTCOME_TO_STATE.get(outcome, "done")

    # Prefer the pre-seeded case's method/path; case_done doesn't carry them.
    existing = db.get_case(run_id, case_id)
    method = existing.method if existing else ""
    path = existing.path if existing else ""

    # FK safety: the cases table has ON DELETE SET NULL FK into dispatches(run_id, id).
    # If dispatch_start hasn't been applied yet (async out-of-order delivery,
    # dropped emit, retry window), setting dispatch_id would trigger an
    # IntegrityError. Drop the reference in that case so the case row still lands.
    dispatch_id_raw = payload.get("dispatch")
    dispatch_id: str | None = None
    if dispatch_id_raw:
        dispatch_id_str = str(dispatch_id_raw)
        if db.get_dispatch(run_id, dispatch_id_str) is not None:
            dispatch_id = dispatch_id_str

    db.upsert_case(
        case_id=case_id,
        run_id=run_id,
        method=method,
        path=path,
        category=payload.get("type") or (existing.category if existing else None),
        dispatch_id=dispatch_id,
        state=state,
        result=payload.get("detail") or payload.get("result"),
        finished_at=int(time.time()),
    )


def _apply_finding(run_id: int, payload: dict[str, Any]) -> None:
    # finding payload currently does not include case_id / method / path.
    # When it does in the future, update the case row here.
    if "case_id" not in payload:
        return
    try:
        case_id = int(payload["case_id"])
    except (TypeError, ValueError):
        return
    existing = db.get_case(run_id, case_id)
    method = existing.method if existing else str(payload.get("method", ""))
    path = existing.path if existing else str(payload.get("path", ""))
    db.upsert_case(
        case_id=case_id,
        run_id=run_id,
        method=method,
        path=path,
        category=payload.get("category") or (existing.category if existing else None),
        state="finding",
        finding_id=str(payload.get("finding_id", "")),
    )


def _apply_phase_enter(run_id: int, payload: dict[str, Any], fallback_phase: str) -> None:
    new_phase = str(payload.get("phase") or fallback_phase or "")
    if not new_phase:
        return
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE runs SET current_phase = ? WHERE id = ?",
            (new_phase, run_id),
        )
        conn.commit()
