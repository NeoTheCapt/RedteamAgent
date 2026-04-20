import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
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
        json={
            "name": "Alpha",
            "provider_id": "openai",
            "model_id": "gpt-5.4",
            "small_model_id": "gpt-5.4-mini",
            "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert create_response.status_code == 201
    created_project = create_response.json()
    assert created_project["id"] == 1
    assert created_project["name"] == "Alpha"
    assert created_project["slug"] == "alpha"
    assert created_project["root_path"] == str(isolate_data_dir / "projects-root" / "alice" / "alpha")
    assert created_project["provider_id"] == "openai"
    assert created_project["model_id"] == "gpt-5.4"
    assert created_project["small_model_id"] == "gpt-5.4-mini"
    assert created_project["base_url"] == "https://api.openai.com/v1"
    assert created_project["api_key_configured"] is True
    assert created_project["auth_configured"] is False
    assert created_project["env_configured"] is False

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
    assert bob_project.json()["root_path"] == str(isolate_data_dir / "projects-root" / "bob" / "demo-workspace")

    duplicate_for_alice = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"name": "Demo Workspace"},
    )
    assert duplicate_for_alice.status_code == 400


def test_update_project_model_settings_preserves_or_clears_api_key():
    client = TestClient(app)
    token = register_and_login(client, "alice")

    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Configurable", "provider_id": "openai", "model_id": "gpt-5.4", "api_key": "sk-test"},
    )
    assert project_response.status_code == 201
    project = project_response.json()
    assert project["api_key_configured"] is True

    # Partial update: only change model-related fields; api_key is not sent so it is preserved
    update_response = client.patch(
        f"/projects/{project['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider_id": "anthropic", "model_id": "claude-sonnet-4-5", "small_model_id": "claude-3-5-haiku", "base_url": "https://api.anthropic.com"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["provider_id"] == "anthropic"
    assert updated["model_id"] == "claude-sonnet-4-5"
    assert updated["small_model_id"] == "claude-3-5-haiku"
    assert updated["base_url"] == "https://api.anthropic.com"
    assert updated["api_key_configured"] is True
    assert updated["auth_configured"] is False
    assert updated["env_configured"] is False

    # Clear api_key by sending empty string
    clear_response = client.patch(
        f"/projects/{project['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_key": ""},
    )
    assert clear_response.status_code == 200
    cleared = clear_response.json()
    assert cleared["api_key_configured"] is False


def test_update_project_auth_and_env_settings():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Auth Env"},
    )
    assert project_response.status_code == 201
    project = project_response.json()

    update_response = client.patch(
        f"/projects/{project['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider_id": "",
            "model_id": "",
            "small_model_id": "",
            "base_url": "",
            "auth_json": '{"headers":{"Authorization":"Bearer test"}}',
            "env_json": '{"HTTP_PROXY":"http://proxy:8080"}',
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["auth_configured"] is True
    assert updated["env_configured"] is True


def test_delete_project_cascades_runs_and_removes_project_root():
    client = TestClient(app)
    token = register_and_login(client, "alice")

    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Disposable"},
    )
    assert project_response.status_code == 201
    project = project_response.json()

    run_response = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert run_response.status_code == 201
    run = run_response.json()

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "command": "opencode run", "started_at": "2026-03-25T00:00:00Z"}),
        encoding="utf-8",
    )
    db.create_event(run["id"], "run.started", "unknown", "runtime", "launcher", "started")

    delete_response = client.request(
        "DELETE",
        f"/projects/{project['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 204
    assert not Path(project["root_path"]).exists()
    assert db.get_project_by_id(project["id"]) is None
    assert db.get_run_by_id(run["id"]) is None
