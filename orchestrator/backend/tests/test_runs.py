import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[3]
backend_root = repo_root / "orchestrator" / "backend"
sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def configure_temp_data_dir(tmp_path: Path) -> None:
    object.__setattr__(settings, "data_dir", tmp_path)


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


def test_create_run_and_list_project_runs(tmp_path):
    configure_temp_data_dir(tmp_path)
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
        tmp_path / "projects" / "alice" / "alpha" / "runs" / "run-0001"
    )

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json() == [run_payload]


def test_run_status_transitions_require_project_ownership(tmp_path):
    configure_temp_data_dir(tmp_path)
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
