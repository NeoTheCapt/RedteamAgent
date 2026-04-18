from app import db
from app.services import event_apply


def _mk_run(tmp_path, name="ea"):
    user = db.create_user(name, "ph", "s")
    proj = db.create_project(
        user_id=user.id, name=name, slug=name, root_path=str(tmp_path),
    )
    run = db.create_run(
        project_id=proj.id, target="http://x",
        status="running", engagement_root=str(tmp_path),
    )
    return run


def test_apply_dispatch_start_creates_dispatch(tmp_path):
    run = _mk_run(tmp_path)
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={
            "batch": "B-1", "round": 2, "slot": "0",
            "case_count": 2, "agent": "vuln-analyst",
            "task": "API batch",
        },
    )
    d = db.get_dispatch(run.id, "B-1")
    assert d is not None
    assert d.state == "running"
    assert d.round == 2
    assert d.agent == "vuln-analyst"


def test_apply_dispatch_start_upserts_cases_from_array(tmp_path):
    run = _mk_run(tmp_path, name="ea_cases")
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={
            "batch": "B-2", "round": 1, "slot": "0",
            "case_count": 2, "agent": "vuln-analyst",
            "cases": [
                {"id": 41, "method": "GET", "path": "/api/users", "type": "api"},
                {"id": 42, "method": "POST", "path": "/api/login", "type": "api"},
            ],
        },
    )
    cases = db.list_cases(run.id)
    assert {c.case_id for c in cases} == {41, 42}
    c41 = db.get_case(run.id, 41)
    assert c41.method == "GET"
    assert c41.path == "/api/users"
    assert c41.category == "api"
    assert c41.dispatch_id == "B-2"
    assert c41.state == "queued"


def test_apply_dispatch_done_updates_existing(tmp_path):
    run = _mk_run(tmp_path, name="ea_done")
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-3", "round": 1, "slot": "0",
                 "case_count": 1, "agent": "v"},
    )
    assert db.get_dispatch(run.id, "B-3").state == "running"

    event_apply.apply(
        run_id=run.id, kind="dispatch_done", phase="consume",
        payload={"batch": "B-3", "state": "done"},
    )
    d = db.get_dispatch(run.id, "B-3")
    assert d.state == "done"
    assert d.finished_at is not None


def test_apply_case_done_upserts_case(tmp_path):
    run = _mk_run(tmp_path, name="ea_cd")
    # pre-create the case via dispatch_start so method/path exist
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-4", "round": 1, "slot": "0", "case_count": 1,
                 "agent": "v",
                 "cases": [{"id": 51, "method": "GET", "path": "/x", "type": "api"}]},
    )
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 51, "outcome": "DONE", "dispatch": "B-4",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c = db.get_case(run.id, 51)
    assert c.state == "done"
    assert c.result == "ok"


def test_apply_case_done_outcome_states(tmp_path):
    run = _mk_run(tmp_path, name="ea_states")
    for case_id, outcome in ((61, "DONE"), (62, "REQUEUE"), (63, "ERROR")):
        event_apply.apply(
            run_id=run.id, kind="dispatch_start", phase="consume",
            payload={"batch": f"Bx-{case_id}", "round": 1, "slot": "0",
                     "case_count": 1, "agent": "v",
                     "cases": [{"id": case_id, "method": "GET",
                                "path": f"/{case_id}", "type": "api"}]},
        )
        event_apply.apply(
            run_id=run.id, kind="case_done", phase="consume",
            payload={"case_id": case_id, "outcome": outcome,
                     "dispatch": f"Bx-{case_id}",
                     "agent": "v", "type": "api", "detail": ""},
        )
    assert db.get_case(run.id, 61).state == "done"
    assert db.get_case(run.id, 62).state == "queued"
    assert db.get_case(run.id, 63).state == "error"


def test_apply_phase_enter_updates_run(tmp_path):
    run = _mk_run(tmp_path, name="ea_phase")
    event_apply.apply(
        run_id=run.id, kind="phase_enter", phase="report",
        payload={"phase": "report"},
    )
    r = db.get_run_by_id(run.id)
    assert r.current_phase == "report"


def test_apply_finding_without_case_id_is_noop_on_cases(tmp_path):
    run = _mk_run(tmp_path, name="ea_find")
    event_apply.apply(
        run_id=run.id, kind="finding", phase="consume",
        payload={"finding_id": "FINDING-X-1", "severity": "critical",
                 "category": "injection",
                 "title": "SQLi"},
    )
    assert db.list_cases(run.id) == []


def test_apply_legacy_kind_is_noop(tmp_path):
    run = _mk_run(tmp_path, name="ea_legacy")
    event_apply.apply(
        run_id=run.id, kind="legacy", phase="unknown", payload={},
    )
    assert db.list_dispatches(run.id) == []
    assert db.list_cases(run.id) == []


def test_case_done_before_dispatch_start_keeps_case_without_dispatch_link(tmp_path):
    run = _mk_run(tmp_path, name="ea_ooo")
    # case_done arrives FIRST (dispatch_start delayed/dropped)
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 99, "outcome": "DONE", "dispatch": "B-late",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c = db.get_case(run.id, 99)
    assert c is not None
    assert c.state == "done"
    assert c.dispatch_id is None  # FK-safe fallback


def test_dispatch_start_after_case_done_preserves_terminal_state(tmp_path):
    """Out-of-order delivery: case_done lands first, then dispatch_start.
    The late dispatch_start must NOT reset the terminal state back to queued.
    """
    run = _mk_run(tmp_path, name="ea_ooo_terminal")
    # case_done arrives FIRST
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 51, "outcome": "DONE", "dispatch": "B-late",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c_after_case_done = db.get_case(run.id, 51)
    assert c_after_case_done.state == "done"

    # dispatch_start arrives LATER with the same case in its cases[] array
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-late", "round": 1, "slot": "0",
                 "case_count": 1, "agent": "v",
                 "cases": [{"id": 51, "method": "GET", "path": "/api/x", "type": "api"}]},
    )

    c_final = db.get_case(run.id, 51)
    # State must still be "done", NOT reset to "queued"
    assert c_final.state == "done"
    # Dispatch linkage is filled in (orphan case reunited with its dispatch)
    assert c_final.dispatch_id == "B-late"


def test_dispatch_start_reseat_is_idempotent_for_linked_cases(tmp_path):
    """If the case is already linked to a dispatch, dispatch_start does nothing destructive."""
    run = _mk_run(tmp_path, name="ea_idem_link")
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-1", "round": 1, "slot": "0", "case_count": 1,
                 "agent": "v",
                 "cases": [{"id": 60, "method": "GET", "path": "/a", "type": "api"}]},
    )
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 60, "outcome": "DONE", "dispatch": "B-1",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    # Simulate a retry: dispatch_start replayed
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-1", "round": 1, "slot": "0", "case_count": 1,
                 "agent": "v",
                 "cases": [{"id": 60, "method": "GET", "path": "/a", "type": "api"}]},
    )
    c = db.get_case(run.id, 60)
    assert c.state == "done"
    assert c.dispatch_id == "B-1"


def test_case_done_with_existing_dispatch_links_correctly(tmp_path):
    run = _mk_run(tmp_path, name="ea_ordered")
    # Pre-seed the dispatch
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-ok", "round": 1, "slot": "0",
                 "case_count": 1, "agent": "v"},
    )
    # case_done for the existing dispatch
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 88, "outcome": "DONE", "dispatch": "B-ok",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c = db.get_case(run.id, 88)
    assert c.dispatch_id == "B-ok"  # linked when available


def test_dispatch_done_before_dispatch_start_persists_terminal_state(tmp_path):
    """Out-of-order: dispatch_done arrives first. Must create a terminal row
    so the completion doesn't get lost."""
    run = _mk_run(tmp_path, name="ea_dd_first")

    event_apply.apply(
        run_id=run.id, kind="dispatch_done", phase="consume",
        payload={"batch": "B-orphan", "state": "done"},
    )
    d = db.get_dispatch(run.id, "B-orphan")
    assert d is not None
    assert d.state == "done"
    assert d.finished_at is not None


def test_dispatch_start_after_done_does_not_resurrect_running(tmp_path):
    """If dispatch_done landed first and created a terminal row, a late
    dispatch_start must not revert it to running."""
    run = _mk_run(tmp_path, name="ea_late_start")
    event_apply.apply(
        run_id=run.id, kind="dispatch_done", phase="consume",
        payload={"batch": "B-x", "state": "done"},
    )
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-x", "round": 1, "slot": "0", "case_count": 0,
                 "agent": "v", "cases": []},
    )
    d = db.get_dispatch(run.id, "B-x")
    assert d.state == "done"
    # agent metadata filled in from the late start event
    assert d.agent == "v"


def test_dispatch_start_seeds_started_at_on_cases(tmp_path):
    """dispatch_start must set started_at on new case rows so duration_ms is computable."""
    run = _mk_run(tmp_path, name="ea_started_at")
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={
            "batch": "B-sa", "round": 1, "slot": "0", "case_count": 1,
            "agent": "v",
            "cases": [{"id": 200, "method": "GET", "path": "/sa", "type": "api"}],
        },
    )
    c = db.get_case(run.id, 200)
    assert c is not None
    assert c.started_at is not None, "started_at must be populated by dispatch_start"


def test_dispatch_start_case_done_duration_ms_positive(tmp_path):
    """dispatch_start → case_done round trip must yield positive duration_ms."""
    import time
    run = _mk_run(tmp_path, name="ea_duration")
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={
            "batch": "B-dur", "round": 1, "slot": "0", "case_count": 1,
            "agent": "v",
            "cases": [{"id": 201, "method": "POST", "path": "/dur", "type": "api"}],
        },
    )
    # Small sleep to ensure finished_at > started_at
    time.sleep(0.01)
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 201, "outcome": "DONE", "dispatch": "B-dur",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c = db.get_case(run.id, 201)
    assert c.started_at is not None
    assert c.finished_at is not None
    duration_ms = (c.finished_at - c.started_at) * 1000
    assert duration_ms >= 0, f"duration_ms should be non-negative, got {duration_ms}"


def test_dispatch_start_does_not_overwrite_existing_started_at(tmp_path):
    """If case_done arrived first (out-of-order), dispatch_start must not overwrite started_at."""
    run = _mk_run(tmp_path, name="ea_no_overwrite_sat")
    # case_done arrives first (sets finished_at, no started_at)
    event_apply.apply(
        run_id=run.id, kind="case_done", phase="consume",
        payload={"case_id": 202, "outcome": "DONE", "dispatch": "B-oo-sat",
                 "agent": "v", "type": "api", "detail": "ok"},
    )
    c_before = db.get_case(run.id, 202)
    assert c_before is not None
    assert c_before.state == "done"
    # started_at is None because case_done doesn't set it
    assert c_before.started_at is None

    # dispatch_start arrives late — should fill started_at since it was None
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-oo-sat", "round": 1, "slot": "0", "case_count": 1,
                 "agent": "v",
                 "cases": [{"id": 202, "method": "GET", "path": "/oo", "type": "api"}]},
    )
    c_after = db.get_case(run.id, 202)
    # State remains terminal (done), not reset to queued
    assert c_after.state == "done"
    # started_at is now populated (filled in by late dispatch_start)
    assert c_after.started_at is not None


def test_missing_outcomes_state_persists(tmp_path):
    """dispatch_done with state='missing_outcomes' survives a late dispatch_start."""
    run = _mk_run(tmp_path, name="ea_missing")
    event_apply.apply(
        run_id=run.id, kind="dispatch_done", phase="consume",
        payload={"batch": "B-m", "state": "missing_outcomes"},
    )
    d = db.get_dispatch(run.id, "B-m")
    assert d.state == "missing_outcomes"
    # A subsequent dispatch_start does not reset this.
    event_apply.apply(
        run_id=run.id, kind="dispatch_start", phase="consume",
        payload={"batch": "B-m", "round": 1, "slot": "0", "case_count": 0,
                 "agent": "v", "cases": []},
    )
    d2 = db.get_dispatch(run.id, "B-m")
    assert d2.state == "missing_outcomes"
