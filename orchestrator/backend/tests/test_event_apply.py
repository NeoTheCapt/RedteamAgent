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
