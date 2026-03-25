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
    register_response = client.post(
        "/auth/register",
        json={"username": username, "password": "secret-password"},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": "secret-password"},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def test_create_project_and_list_only_owner_projects(tmp_path):
    configure_temp_data_dir(tmp_path)
    client = TestClient(app)

    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")

    create_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"name": "Alpha"},
    )
    assert create_response.status_code == 201
    created_project = create_response.json()
    assert created_project["id"] == 1
    assert created_project["name"] == "Alpha"
    assert created_project["slug"] == "alpha"
    assert created_project["root_path"] == str(tmp_path / "projects" / "alice" / "alpha")

    alice_projects = client.get(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert alice_projects.status_code == 200
    assert alice_projects.json() == [created_project]

    bob_projects = client.get(
        "/projects",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert bob_projects.status_code == 200
    assert bob_projects.json() == []


def test_project_roots_are_isolated_per_user_and_slug_conflict_is_rejected(tmp_path):
    configure_temp_data_dir(tmp_path)
    client = TestClient(app)

    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")

    alice_project = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"name": "Demo Workspace"},
    )
    assert alice_project.status_code == 201

    bob_project = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"name": "Demo Workspace"},
    )
    assert bob_project.status_code == 201
    assert bob_project.json()["root_path"] == str(tmp_path / "projects" / "bob" / "demo-workspace")

    duplicate_for_alice = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"name": "Demo Workspace"},
    )
    assert duplicate_for_alice.status_code == 400
