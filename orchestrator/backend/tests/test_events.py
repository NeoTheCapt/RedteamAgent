import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.event import Event
from app.services.events import _project_process_log_events

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


def test_log_artifact_projection_uses_latest_known_phase_for_later_source_analyzer_batches():
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
            "event_type": "task.started",
            "phase": "consume-test",
            "task_name": "bash",
            "agent_name": "operator",
            "summary": "Dispatch page batch",
        },
        {
            "event_type": "artifact.updated",
            "phase": "unknown",
            "task_name": "log.md",
            "agent_name": "source-analyzer",
            "summary": "Source analysis start",
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
        event["event_type"] == "task.started"
        and event["phase"] == "consume-test"
        and event["task_name"] == "source-analyzer"
        for event in events
    )


def test_log_artifact_projection_prefers_agent_phase_for_exploit_developer():
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
            "agent_name": "exploit-developer",
            "summary": "Exploit start",
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
        event["event_type"] == "task.started"
        and event["phase"] == "exploit"
        and event["task_name"] == "exploit-developer"
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


def test_process_log_task_tool_parses_current_phase_prompt_format(tmp_path: Path):
    run_root = tmp_path / "current-phase"
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text(
        (
            '{"type":"tool_use","timestamp":1774816996799,'
            '"part":{"tool":"task","state":{"status":"completed","input":'
            '{"description":"Triage API batch","subagent_type":"vulnerability-analyst",'
            '"prompt":"Authorized lab target: http://host.docker.internal:8000\\nCurrent phase: consume_test\\nAssigned batch file: /workspace/api_batch_001.json\\n"}'
            '}}}\n'
        ),
        encoding="utf-8",
    )

    events = _project_process_log_events(run_id=1, run_root=run_root, events=[])

    assert any(
        event.event_type == "task.started"
        and event.phase == "consume-test"
        and event.agent_name == "vulnerability-analyst"
        and event.summary == "Triage API batch"
        for event in events
    )
    assert any(
        event.event_type == "task.completed"
        and event.phase == "consume-test"
        and event.agent_name == "vulnerability-analyst"
        and event.summary == "Triage API batch completed"
        for event in events
    )


def test_process_log_task_projection_upgrades_weaker_synthetic_log_phase(tmp_path: Path):
    run_root = tmp_path / "phase-upgrade"
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    created_at = "2026-03-29 20:42:47"
    (runtime_dir / "process.log").write_text(
        (
            '{"type":"tool_use","timestamp":1774816967000,'
            '"part":{"tool":"task","state":{"status":"completed","input":'
            '{"description":"Exploit start","subagent_type":"exploit-developer",'
            '"prompt":"**Target**: https://www.okx.com\\n**Phase**: Exploit\\n"}'
            '}}}\n'
        ),
        encoding="utf-8",
    )
    synthetic_events = [
        Event(
            id=-1,
            run_id=1,
            event_type="task.started",
            phase="recon",
            task_name="exploit-developer",
            agent_name="exploit-developer",
            summary="Exploit start",
            created_at=created_at,
        )
    ]

    events = _project_process_log_events(run_id=1, run_root=run_root, events=synthetic_events)
    upgraded = [
        event
        for event in events
        if event.event_type == "task.started"
        and event.agent_name == "exploit-developer"
        and event.summary == "Exploit start"
        and event.created_at == created_at
    ]

    assert len(upgraded) == 1
    assert upgraded[0].phase == "exploit"
    assert upgraded[0].id == -1


def test_opencode_log_subagent_creation_is_projected_into_active_task_timeline(tmp_path: Path):
    run_root = tmp_path / "opencode-subagent"
    log_dir = run_root / "opencode-home" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "2026-04-02T020938.log").write_text(
        (
            "INFO  2026-04-02T02:21:20 +5ms service=session "
            "id=ses_child slug=calm-rocket version=1.3.7 projectID=global directory=/workspace "
            "parentID=ses_parent title=Analyze api batch (@vulnerability-analyst subagent) "
            'permission=[{"permission":"todowrite","pattern":"*","action":"deny"}] '
            'time={"created":1775096480142,"updated":1775096480142} created\n'
        ),
        encoding="utf-8",
    )

    events = _project_process_log_events(run_id=1, run_root=run_root, events=[])

    assert any(
        event.event_type == "task.started"
        and event.phase == "consume-test"
        and event.agent_name == "vulnerability-analyst"
        and event.task_name == "vulnerability-analyst"
        and event.summary == "Analyze api batch (@vulnerability-analyst subagent)"
        and event.created_at == "2026-04-02 02:21:20"
        for event in events
    )



def test_process_log_projection_keeps_utc_ordering_even_when_local_timezone_is_not_utc():
    client = TestClient(app)

    token = register_and_login(client, "bob")
    project = create_project(client, token, name="Timezone Check")
    run = create_run(client, token, project["id"])

    workspace = Path(run["engagement_root"]) / "workspace"
    active_dir = workspace / "engagements" / "2026-03-25-000000-example"
    active_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text("engagements/2026-03-25-000000-example", encoding="utf-8")
    (active_dir / "scope.json").write_text('{"current_phase":"recon"}', encoding="utf-8")

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

    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Singapore"
        time.tzset()

        response = client.get(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        events = response.json()
        projected = [
            event for event in events
            if event["event_type"] == "task.started" and event["agent_name"] == "recon-specialist"
        ]
        assert projected
        assert projected[0]["created_at"] == "2026-03-25 06:01:54"
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
