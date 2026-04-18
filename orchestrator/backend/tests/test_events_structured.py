import json
from fastapi.testclient import TestClient
from app.main import app
from app import db


def _register(client, username="alice"):
    client.post("/auth/register", json={"username": username, "password": "secret-password"})
    r = client.post("/auth/login", json={"username": username, "password": "secret-password"})
    return r.json()["access_token"]


def _create_project_and_run(client, token, isolate_data_dir, suffix="p"):
    p = client.post("/projects",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": f"proj-{suffix}"}).json()
    proj = db.get_project_by_id(p["id"])
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(isolate_data_dir))
    return p, run


def test_post_event_accepts_structured_fields(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "alice_c1")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "alice")

    resp = client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "dispatch.started",
            "phase": "consume",
            "task_name": "B-17",
            "agent_name": "vuln-analyst:s0",
            "summary": "API batch",
            "kind": "dispatch_start",
            "level": "info",
            "payload": {
                "batch": "B-17", "round": 2, "slot": "s0",
                "case_count": 5, "agent": "vuln-analyst",
            },
        },
    )
    assert resp.status_code == 201, resp.text

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT kind, level, payload_json FROM events WHERE run_id = ?",
            (run.id,),
        ).fetchone()
    assert row["kind"] == "dispatch_start"
    assert row["level"] == "info"
    assert json.loads(row["payload_json"])["batch"] == "B-17"


def test_post_event_without_kind_is_legacy(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "bob_c1")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "bob")

    resp = client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.status", "phase": "consume",
            "task_name": "x", "agent_name": "a", "summary": "s",
        },
    )
    assert resp.status_code == 201

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT kind, level, payload_json FROM events WHERE run_id = ?",
            (run.id,),
        ).fetchone()
    assert row["kind"] == "legacy"
    assert row["level"] == "info"
    assert row["payload_json"] == "{}"


def test_post_dispatch_start_creates_dispatch_row(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "dan_c2")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "dan")
    h = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers=h,
        json={
            "event_type": "dispatch.started", "phase": "consume",
            "task_name": "B-1", "agent_name": "vuln:s0",
            "summary": "batch", "kind": "dispatch_start",
            "payload": {
                "batch": "B-1", "round": 1, "slot": "0",
                "agent": "vuln-analyst", "case_count": 2,
                "cases": [
                    {"id": 1, "method": "GET", "path": "/a", "type": "api"},
                    {"id": 2, "method": "GET", "path": "/b", "type": "api"},
                ],
            },
        },
    )
    assert r.status_code == 201
    d = db.get_dispatch(run.id, "B-1")
    assert d is not None
    assert d.agent == "vuln-analyst"

    cases = db.list_cases(run.id)
    assert {c.case_id for c in cases} == {1, 2}


def test_post_event_handles_empty_payload(isolate_data_dir):
    """kind + level but no payload => payload defaults to {}."""
    client = TestClient(app)
    token = _register(client, "carol_c1")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "carol")

    resp = client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "phase.entered", "phase": "report",
            "task_name": "phase-transition", "agent_name": "operator",
            "summary": "enter report",
            "kind": "phase_enter", "level": "info",
        },
    )
    assert resp.status_code == 201

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT kind, level, payload_json FROM events WHERE run_id = ?",
            (run.id,),
        ).fetchone()
    assert row["kind"] == "phase_enter"
    assert row["payload_json"] == "{}"


def test_get_events_returns_kind_level_payload(isolate_data_dir):
    """REST GET /events must return kind/level/payload so the EventsTab filter works."""
    client = TestClient(app)
    token = _register(client, "eve_c1")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "eve")
    h = {"Authorization": f"Bearer {token}"}

    # POST a structured event with all three fields
    client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers=h,
        json={
            "event_type": "dispatch.started", "phase": "consume",
            "task_name": "B-99", "agent_name": "vuln:s0",
            "summary": "batch 99", "kind": "dispatch_start", "level": "info",
            "payload": {"batch": "B-99", "round": 3, "slot": "0",
                        "agent": "vuln-analyst", "case_count": 1},
        },
    )

    # GET events via REST
    r = client.get(f"/projects/{p['id']}/runs/{run.id}/events", headers=h)
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    ev = events[-1]
    # kind must be present and correct (level "info" is the default, returned as None)
    assert ev["kind"] == "dispatch_start"
    # level "info" is the default; REST normalizes it to None (frontend uses ?? "info")
    assert ev["level"] is None
    # payload must be present and include the batch key
    assert ev["payload"] is not None
    assert ev["payload"]["batch"] == "B-99"


def test_get_events_legacy_kind_returns_null_kind(isolate_data_dir):
    """Legacy events (no kind/level) return null for those optional fields."""
    client = TestClient(app)
    token = _register(client, "frank_c1")
    p, run = _create_project_and_run(client, token, isolate_data_dir, "frank")
    h = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/projects/{p['id']}/runs/{run.id}/events",
        headers=h,
        json={
            "event_type": "task.status", "phase": "consume",
            "task_name": "x", "agent_name": "a", "summary": "s",
        },
    )

    r = client.get(f"/projects/{p['id']}/runs/{run.id}/events", headers=h)
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    ev = events[0]
    # legacy kind maps to None in REST response (frontend uses ?? "legacy")
    assert ev["kind"] is None
    assert ev["payload"] is None
