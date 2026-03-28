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


def write_artifact(run: dict, name: str, content: str) -> None:
    Path(run["engagement_root"], name).write_text(content, encoding="utf-8")


def write_engagement_artifact(run: dict, name: str, content: str) -> Path:
    workspace = Path(run["engagement_root"], "workspace")
    engagements = workspace / "engagements"
    active_name = "2026-03-25-000000-example"
    active_dir = engagements / active_name
    active_dir.mkdir(parents=True, exist_ok=True)
    (engagements / ".active").write_text(f"engagements/{active_name}", encoding="utf-8")
    artifact_path = active_dir / name
    artifact_path.write_text(content, encoding="utf-8")
    return artifact_path


def test_list_artifacts_marks_sensitive_files_and_presence():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    write_artifact(run, "log.md", "# Log\n")
    write_artifact(run, "auth.json", '{"token":"secret"}\n')
    Path(run["engagement_root"], "runtime").mkdir(parents=True, exist_ok=True)
    Path(run["engagement_root"], "runtime", "process.log").write_text("runtime output\n", encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = {artifact["name"]: artifact for artifact in response.json()}

    assert payload["log.md"]["exists"] is True
    assert payload["log.md"]["sensitive"] is False
    assert payload["process.log"]["exists"] is True
    assert payload["process.log"]["sensitive"] is False
    assert payload["auth.json"]["exists"] is True
    assert payload["auth.json"]["sensitive"] is True
    assert payload["report.md"]["exists"] is False


def test_read_artifact_returns_content_and_enforces_ownership():
    client = TestClient(app)
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = create_project(client, alice_token)
    run = create_run(client, alice_token, project["id"])

    write_artifact(run, "findings.md", "# Findings\n")

    owner_response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts/findings.md",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["media_type"] == "text/markdown"
    assert owner_response.json()["content"] == "# Findings\n"

    other_user_response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts/findings.md",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert other_user_response.status_code == 404


def test_read_runtime_process_log_as_artifact():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    runtime_dir = Path(run["engagement_root"], "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text("line one\nline two\n", encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts/process.log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["media_type"] == "text/plain"
    assert response.json()["content"] == "line one\nline two\n"


def test_read_active_engagement_artifact_from_workspace():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    write_engagement_artifact(run, "log.md", "# Engagement Log\n")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts/log.md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "# Engagement Log\n"


def test_read_latest_engagement_artifact_without_active_marker():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    workspace = Path(run["engagement_root"], "workspace")
    active_dir = workspace / "engagements" / "2026-03-25-000000-example"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "log.md").write_text("# Latest Engagement Log\n", encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts/log.md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "# Latest Engagement Log\n"
