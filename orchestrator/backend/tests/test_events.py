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


def create_run(client: TestClient, token: str, project_id: int, target: str = "https://example.com") -> dict:
    response = client.post(
        f"/projects/{project_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": target},
    )
    assert response.status_code == 201
    return response.json()


def test_persist_events_and_list_them_by_run(tmp_path):
    configure_temp_data_dir(tmp_path)
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    event_payload = {
        "event_type": "phase.started",
        "phase": "recon",
        "task_name": "recon-specialist",
        "agent_name": "recon-specialist",
        "summary": "Recon phase started",
    }
    create_event = client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json=event_payload,
    )
    assert create_event.status_code == 201
    assert create_event.json()["event_type"] == "phase.started"

    list_events = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_events.status_code == 200
    assert len(list_events.json()) == 1
    assert list_events.json()[0]["summary"] == "Recon phase started"


def test_latest_phase_and_task_state_summary(tmp_path):
    configure_temp_data_dir(tmp_path)
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    events = [
        {
            "event_type": "phase.started",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "operator",
            "summary": "Recon started",
        },
        {
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon worker started",
        },
        {
            "event_type": "task.completed",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon worker finished",
        },
        {
            "event_type": "phase.completed",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "operator",
            "summary": "Recon completed",
        },
    ]

    for event in events:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    summary = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/events/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200
    assert summary.json() == {
        "latest_phase": {
            "phase": "recon",
            "event_type": "phase.completed",
            "summary": "Recon completed",
        },
        "latest_task": {
            "phase": "recon",
            "task_name": "recon-specialist",
            "event_type": "task.completed",
            "summary": "Recon worker finished",
        },
    }
