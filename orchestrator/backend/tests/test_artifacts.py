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


def test_list_artifacts_marks_sensitive_files_and_presence():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    write_artifact(run, "log.md", "# Log\n")
    write_artifact(run, "auth.json", '{"token":"secret"}\n')

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/artifacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = {artifact["name"]: artifact for artifact in response.json()}

    assert payload["log.md"]["exists"] is True
    assert payload["log.md"]["sensitive"] is False
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
