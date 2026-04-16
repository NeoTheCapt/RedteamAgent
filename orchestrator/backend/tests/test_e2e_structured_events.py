from fastapi.testclient import TestClient
from app.main import app
from app import db


def test_dispatch_to_finding_flow_populates_all_tables(isolate_data_dir):
    client = TestClient(app)
    client.post("/auth/register", json={"username": "e2e", "password": "secret-password"})
    token = client.post("/auth/login",
                        json={"username": "e2e", "password": "secret-password"}).json()["access_token"]
    user = db.get_user_by_username("e2e")
    proj = db.create_project(user_id=user.id, name="e2e", slug="e2e",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(isolate_data_dir))
    h = {"Authorization": f"Bearer {token}"}

    events = [
        # Phase enters consume
        {
            "event_type": "phase.entered", "phase": "consume",
            "task_name": "phase-transition", "agent_name": "operator",
            "summary": "enter consume",
            "kind": "phase_enter", "level": "info",
            "payload": {"phase": "consume"},
        },
        # Dispatch starts, carries cases[] array (B2.1)
        {
            "event_type": "dispatch.started", "phase": "consume",
            "task_name": "B-1", "agent_name": "vulnerability-analyst:s0",
            "summary": "API batch B-1 (2 cases)",
            "kind": "dispatch_start", "level": "info",
            "payload": {
                "batch": "B-1", "round": 1, "slot": "0",
                "case_count": 2, "type": "api",
                "agent": "vulnerability-analyst",
                "cases": [
                    {"id": 1, "method": "GET", "path": "/api/products", "type": "api"},
                    {"id": 2, "method": "GET", "path": "/api/search", "type": "api"},
                ],
            },
        },
        # First case — done, no finding
        {
            "event_type": "case.done", "phase": "consume",
            "task_name": "case-1", "agent_name": "vulnerability-analyst:s0",
            "summary": "GET /api/products — done",
            "kind": "case_done", "level": "info",
            "payload": {
                "case_id": 1, "outcome": "DONE", "dispatch": "B-1",
                "agent": "vulnerability-analyst",
                "agent_tag": "vulnerability-analyst:s0",
                "type": "api", "detail": "no injection", "round": 1,
            },
        },
        # Second case — finding
        {
            "event_type": "case.done", "phase": "consume",
            "task_name": "case-2", "agent_name": "vulnerability-analyst:s0",
            "summary": "GET /api/search — finding",
            "kind": "case_done", "level": "info",
            "payload": {
                "case_id": 2, "outcome": "DONE", "dispatch": "B-1",
                "agent": "vulnerability-analyst",
                "agent_tag": "vulnerability-analyst:s0",
                "type": "api",
                "detail": "/api/search — FINDING-VA-003 union-based SQLi",
                "round": 1,
            },
        },
        # Finding event (case_done already marked state=done; finding comes separately;
        # since append_finding.sh currently doesn't carry case_id, event_apply.apply(finding)
        # is a no-op on cases — we only check that the event persists and that cases show
        # state=done from the prior case_done. This matches current agent behavior.)
        {
            "event_type": "finding.created", "phase": "consume",
            "task_name": "FINDING-VA-003",
            "agent_name": "vulnerability-analyst:s0",
            "summary": "Union-based SQL Injection",
            "kind": "finding", "level": "info",
            "payload": {
                "finding_id": "FINDING-VA-003",
                "severity": "critical",
                "category": "injection",
                "title": "Union-based SQL Injection in /api/search",
            },
        },
        # Dispatch completes
        {
            "event_type": "dispatch.done", "phase": "consume",
            "task_name": "B-1", "agent_name": "vulnerability-analyst:s0",
            "summary": "batch B-1 recorded (2 cases)",
            "kind": "dispatch_done", "level": "info",
            "payload": {"batch": "B-1", "case_count": 2, "state": "done"},
        },
    ]

    for evt in events:
        r = client.post(
            f"/projects/{proj.id}/runs/{run.id}/events",
            headers=h,
            json=evt,
        )
        assert r.status_code == 201, f"POST {evt['kind']}: {r.text}"

    # --- Verify runs row ---
    run_fetched = db.get_run_by_id(run.id)
    assert run_fetched.current_phase == "consume"

    # --- Verify dispatch row ---
    dispatch = db.get_dispatch("B-1")
    assert dispatch is not None
    assert dispatch.state == "done"
    assert dispatch.finished_at is not None
    assert dispatch.round == 1
    assert dispatch.agent == "vulnerability-analyst"

    # --- Verify cases rows ---
    cases = db.list_cases(run.id)
    assert {c.case_id for c in cases} == {1, 2}
    c1 = db.get_case(run.id, 1)
    c2 = db.get_case(run.id, 2)
    assert c1.state == "done"
    assert c1.method == "GET"
    assert c1.path == "/api/products"
    assert c2.state == "done"
    assert c2.method == "GET"
    assert c2.path == "/api/search"

    # --- Verify events row count (6 structured + any legacy bookkeeping) ---
    with db.get_connection() as conn:
        structured_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND kind != 'legacy'",
            (run.id,),
        ).fetchone()[0]
    assert structured_count == 6

    # --- Verify finding event is persisted with full payload ---
    with db.get_connection() as conn:
        finding_row = conn.execute(
            "SELECT payload_json FROM events WHERE run_id = ? AND kind = 'finding'",
            (run.id,),
        ).fetchone()
    import json
    payload = json.loads(finding_row["payload_json"])
    assert payload["finding_id"] == "FINDING-VA-003"
    assert payload["severity"] == "critical"

    # --- Verify summary endpoint reflects aggregates ---
    summary = client.get(f"/projects/{proj.id}/runs/{run.id}/summary",
                         headers=h).json()
    assert summary["dispatches"]["total"] == 1
    assert summary["dispatches"]["done"] == 1
    assert summary["dispatches"]["active"] == 0
    assert summary["cases"]["total"] == 2
    assert summary["cases"]["done"] == 2

    # --- Verify dispatches endpoint returns the record ---
    disp_list = client.get(f"/projects/{proj.id}/runs/{run.id}/dispatches",
                           headers=h).json()
    assert len(disp_list) == 1
    assert disp_list[0]["id"] == "B-1"
    assert disp_list[0]["state"] == "done"

    # --- Verify cases endpoint returns both rows ---
    case_list = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                           headers=h).json()
    assert [c["case_id"] for c in case_list] == [1, 2]
    assert all(c["state"] == "done" for c in case_list)
