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


def test_websocket_receives_new_event_payload():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    with client.websocket_connect(f"/ws/projects/{project['id']}/runs/{run['id']}?token={token}") as websocket:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "event_type": "task.started",
                "phase": "recon",
                "task_name": "recon-specialist",
                "agent_name": "recon-specialist",
                "summary": "Recon task started",
            },
        )
        assert response.status_code == 201

        payload = websocket.receive_json()
        assert payload["type"] == "event.created"
        assert payload["event"]["event_type"] == "task.started"
        assert payload["event"]["summary"] == "Recon task started"


def test_websocket_receives_run_status_updates():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    with client.websocket_connect(f"/ws/projects/{project['id']}/runs/{run['id']}?token={token}") as websocket:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/status",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "running"},
        )
        assert response.status_code == 200

        payload = websocket.receive_json()
        assert payload["type"] == "run.status.updated"
        assert payload["run"]["status"] == "running"
