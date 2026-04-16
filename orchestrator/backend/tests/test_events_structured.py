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
