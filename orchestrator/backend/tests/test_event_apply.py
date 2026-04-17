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
