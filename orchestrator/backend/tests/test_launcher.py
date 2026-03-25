import json
from pathlib import Path

from fastapi.testclient import TestClient

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


def create_run(client: TestClient, token: str, project_id: int, target: str = "https://example.com") -> dict:
    response = client.post(
        f"/projects/{project_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": target},
    )
    assert response.status_code == 201
    return response.json()


def test_create_run_prepares_isolated_runtime_directories():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    run_root = Path(run["engagement_root"])
    assert run_root.exists()
    assert (run_root / "runtime").is_dir()
    assert (run_root / "workspace").is_dir()
    assert (run_root / "opencode-home").is_dir()

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == run["id"]
    assert metadata["target"] == "https://example.com"
    assert metadata["engagement_root"] == run["engagement_root"]


def test_each_run_gets_its_own_runtime_root():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    first_run = create_run(client, token, project["id"], "https://one.example")
    second_run = create_run(client, token, project["id"], "https://two.example")

    assert first_run["engagement_root"] != second_run["engagement_root"]
    assert Path(first_run["engagement_root"], "run.json").exists()
    assert Path(second_run["engagement_root"], "run.json").exists()
