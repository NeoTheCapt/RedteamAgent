import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app

def register_and_login(client: TestClient, username: str) -> str:
    client.post("/auth/register", json={"username": username, "password": "secret-password"})
    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": "secret-password"},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def create_project(client: TestClient, token: str, name: str = "Alpha") -> dict:
    response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


def test_create_run_and_list_project_runs(isolate_data_dir):
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run_payload = create_run.json()
    assert run_payload["id"] == 1
    assert run_payload["status"] == "queued"
    assert run_payload["target"] == "https://example.com"
    assert run_payload["engagement_root"] == str(
        isolate_data_dir / "projects-root" / "alice" / "alpha" / "runs" / "run-0001"
    )

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json() == [run_payload]


def test_run_status_transitions_require_project_ownership():
    client = TestClient(app)

    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = create_project(client, alice_token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"target": "https://example.com"},
    )
    run_id = create_run.json()["id"]

    forbidden = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"status": "running"},
    )
    assert forbidden.status_code == 404

    running = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"status": "running"},
    )
    assert running.status_code == 200
    assert running.json()["status"] == "running"

    completed = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_list_runs_marks_stale_running_process_as_failed():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "command": "opencode run", "started_at": "2026-03-25T00:00:00Z"}),
        encoding="utf-8",
    )
    db.update_run_status(run["id"], "running")

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"


def test_delete_run_removes_runtime_files_and_db_records():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "command": "opencode run", "started_at": "2026-03-25T00:00:00Z"}),
        encoding="utf-8",
    )
    db.create_event(run["id"], "run.started", "unknown", "runtime", "launcher", "started")

    response = client.request(
        "DELETE",
        f"/projects/{project['id']}/runs/{run['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    assert not run_root.exists()
    assert db.get_run_by_id(run["id"]) is None
    assert db.list_events_for_run(run["id"]) == []
