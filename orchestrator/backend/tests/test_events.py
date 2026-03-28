from fastapi.testclient import TestClient
from pathlib import Path

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


def test_persist_events_and_list_them_by_run():
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


def test_latest_phase_and_task_state_summary():
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


def test_log_artifact_events_are_projected_into_phase_and_task_timeline():
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    raw_events = [
        {
            "event_type": "artifact.updated",
            "phase": "unknown",
            "task_name": "log.md",
            "agent_name": "operator",
            "summary": "Engagement start",
        },
        {
            "event_type": "artifact.updated",
            "phase": "unknown",
            "task_name": "log.md",
            "agent_name": "source-analyzer",
            "summary": "Source analysis start",
        },
        {
            "event_type": "artifact.updated",
            "phase": "unknown",
            "task_name": "log.md",
            "agent_name": "source-analyzer",
            "summary": "Source analysis summary",
        },
    ]

    for event in raw_events:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    events = response.json()

    assert any(
        event["event_type"] == "phase.started" and event["phase"] == "recon"
        for event in events
    )
    assert any(
        event["event_type"] == "task.started"
        and event["phase"] == "recon"
        and event["task_name"] == "source-analyzer"
        for event in events
    )
    assert any(
        event["event_type"] == "task.completed"
        and event["phase"] == "recon"
        and event["task_name"] == "source-analyzer"
        for event in events
    )


def test_process_log_task_tool_is_projected_into_task_timeline():
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    runtime_dir = Path(run["engagement_root"]) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text(
        (
            '{"type":"tool_use","timestamp":1774418514213,'
            '"part":{"tool":"task","state":{"status":"completed","input":'
            '{"description":"Recon - fingerprint target","subagent_type":"recon-specialist",'
            '"prompt":"**Target**: https://example.com\\n**Phase**: Recon\\n"}'
            '}}}\n'
        ),
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    events = response.json()

    assert any(
        event["event_type"] == "task.started"
        and event["phase"] == "recon"
        and event["agent_name"] == "recon-specialist"
        for event in events
    )
    assert any(
        event["event_type"] == "task.completed"
        and event["phase"] == "recon"
        and event["agent_name"] == "recon-specialist"
        for event in events
    )


def test_process_log_regular_tool_use_is_projected_into_operator_timeline():
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    workspace = Path(run["engagement_root"]) / "workspace"
    active_dir = workspace / "engagements" / "2026-03-25-000000-example"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "scope.json").write_text('{"current_phase":"recon"}', encoding="utf-8")

    runtime_dir = Path(run["engagement_root"]) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text(
        (
            '{"type":"tool_use","timestamp":1774420227850,'
            '"part":{"tool":"bash","title":"Check workspace contents","state":{"status":"completed","input":'
            '{"description":"Check workspace contents","command":"ls -la"}'
            '}}}\n'
        ),
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    events = response.json()

    assert any(
        event["event_type"] == "task.started"
        and event["phase"] == "recon"
        and event["agent_name"] == "operator"
        and event["task_name"] == "bash"
        for event in events
    )
