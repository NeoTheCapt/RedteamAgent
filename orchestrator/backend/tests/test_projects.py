from fastapi.testclient import TestClient

from app.main import app

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


def test_create_project_and_list_only_owner_projects(isolate_data_dir):
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
    assert created_project["root_path"] == str(isolate_data_dir / "projects" / "alice" / "alpha")

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


def test_project_roots_are_isolated_per_user_and_slug_conflict_is_rejected(isolate_data_dir):
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
    assert bob_project.json()["root_path"] == str(isolate_data_dir / "projects" / "bob" / "demo-workspace")

    duplicate_for_alice = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"name": "Demo Workspace"},
    )
    assert duplicate_for_alice.status_code == 400
