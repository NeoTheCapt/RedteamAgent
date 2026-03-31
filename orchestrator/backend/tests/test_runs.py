import json
import os
import sqlite3
from pathlib import Path
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import db
from app.db import database_path
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


def test_create_run_and_list_project_runs(isolate_data_dir):
    client = TestClient(app)

    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run_payload = create_run.json()
    assert run_payload["id"] == 1
    assert run_payload["status"] == "queued"
    assert run_payload["target"] == "https://example.com"
    assert run_payload["engagement_root"] == str(
        isolate_data_dir / "projects-root" / "alice" / "alpha" / "runs" / "run-0001"
    )
    assert run_payload["created_at"]
    assert run_payload["updated_at"]

    run_metadata = json.loads((Path(run_payload["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert run_metadata["id"] == run_payload["id"]
    assert run_metadata["run_id"] == run_payload["id"]
    assert run_metadata["created_at"] == run_payload["created_at"]
    assert run_metadata["updated_at"] == run_payload["updated_at"]

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json() == [run_payload]


def test_run_status_transitions_require_project_ownership():
    client = TestClient(app)

    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = create_project(client, alice_token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"target": "https://example.com"},
    )
    run_id = create_run.json()["id"]

    forbidden = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"status": "running"},
    )
    assert forbidden.status_code == 404

    running = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"status": "running"},
    )
    assert running.status_code == 200
    assert running.json()["status"] == "running"

    completed = client.post(
        f"/projects/{project['id']}/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["created_at"]
    assert completed.json()["updated_at"]

    run_root = Path(completed.json()["engagement_root"])
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["id"] == run_id
    assert metadata["run_id"] == run_id
    assert metadata["created_at"] == completed.json()["created_at"]
    assert metadata["updated_at"] == completed.json()["updated_at"]


def test_list_runs_keeps_running_container_alive_across_backend_restart(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps(
            {
                "run_id": run["id"],
                "container_name": f"redteam-orch-run-{run['id']:04d}",
                "launcher_pid": 999999,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert stopped == []



def test_list_runs_syncs_updated_at_from_live_workflow_activity(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )

    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text("recent activity\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('processing')")
        connection.commit()

    recent_activity = datetime.now(UTC).replace(microsecond=0)
    recent_epoch = recent_activity.timestamp()
    os.utime(scope_path, (recent_epoch, recent_epoch))
    os.utime(engagement_dir / "log.md", (recent_epoch, recent_epoch))

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    payload = runs_response.json()[0]
    assert payload["status"] == "running"
    assert payload["updated_at"] == recent_activity.strftime("%Y-%m-%d %H:%M:%S")
    assert stopped == []

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["updated_at"] == payload["updated_at"]



def test_list_runs_projects_live_agent_state_into_run_metadata(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "http://127.0.0.1:8000"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-local"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-local\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text("# Engagement Log\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(type, status, assigned_agent, source) VALUES ('api', 'processing', 'vulnerability-analyst', 'katana')"
        )
        connection.commit()

    event_response = client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "consume-test",
            "task_name": "vulnerability-analyst",
            "agent_name": "vulnerability-analyst",
            "summary": "Analysis start",
        },
    )
    assert event_response.status_code == 201

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["current_action"] == {
        "phase": "consume-test",
        "task_name": "vulnerability-analyst",
        "agent_name": "vulnerability-analyst",
        "summary": "Analysis start",
    }
    consume_phase = next(item for item in metadata["phase_waterfall"] if item["phase"] == "consume-test")
    assert consume_phase["state"] == "active"
    assert consume_phase["active_agents"] == 1
    agent_card = next(item for item in metadata["agents"] if item["agent_name"] == "vulnerability-analyst")
    assert agent_card["status"] == "active"
    assert agent_card["summary"] == "Analysis start"



def test_list_runs_syncs_updated_at_from_latest_event_when_newer_than_workflow_files(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )

    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text("recent activity\n", encoding="utf-8")
    stale_activity = datetime(2026, 3, 25, 0, 0, 0, tzinfo=UTC)
    stale_epoch = stale_activity.timestamp()
    os.utime(scope_path, (stale_epoch, stale_epoch))
    os.utime(engagement_dir / "log.md", (stale_epoch, stale_epoch))

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.execute(
            "INSERT INTO events(run_id, event_type, phase, task_name, agent_name, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], "task.completed", "consume-test", "source-analyzer", "source-analyzer", "Late event", "2026-03-30 09:40:45"),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    payload = runs_response.json()[0]
    assert payload["status"] == "running"
    assert payload["updated_at"] == "2026-03-30 09:40:45"
    assert stopped == []

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["updated_at"] == payload["updated_at"]



def test_list_runs_repairs_future_skewed_updated_at_from_live_workflow_activity(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )

    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text("recent activity\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('processing')")
        connection.commit()

    recent_activity = datetime.now(UTC).replace(microsecond=0)
    recent_epoch = recent_activity.timestamp()
    os.utime(scope_path, (recent_epoch, recent_epoch))
    os.utime(engagement_dir / "log.md", (recent_epoch, recent_epoch))

    future_skewed = recent_activity + timedelta(hours=8)
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE id = ?",
            (future_skewed.strftime("%Y-%m-%d %H:%M:%S"), run["id"]),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    payload = runs_response.json()[0]
    assert payload["status"] == "running"
    assert payload["updated_at"] == recent_activity.strftime("%Y-%m-%d %H:%M:%S")
    assert stopped == []

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["updated_at"] == payload["updated_at"]



def test_list_runs_ignores_future_timestamps_embedded_in_process_log_text(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text(
        "Exploit response included paymentDue=2026-04-14T06:09:11.080Z but runtime is still active\n",
        encoding="utf-8",
    )
    recent_activity = datetime.now(UTC).replace(microsecond=0)
    recent_epoch = recent_activity.timestamp()
    os.utime(process_log, (recent_epoch, recent_epoch))

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    payload = runs_response.json()[0]
    assert payload["status"] == "running"
    assert payload["updated_at"] == recent_activity.strftime("%Y-%m-%d %H:%M:%S")
    assert stopped == []

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["updated_at"] == payload["updated_at"]



def test_list_runs_marks_stale_running_process_as_failed():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "command": "opencode run", "started_at": "2026-03-25T00:00:00Z"}),
        encoding="utf-8",
    )
    db.update_run_status(run["id"], "running")
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"


def test_list_runs_keeps_recent_running_process_during_startup_grace_window(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"


def test_list_runs_preserves_running_status_when_runtime_lookup_is_unavailable(monkeypatch):
    from app.services.launcher import RUNTIME_PID_LOOKUP_UNAVAILABLE

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: RUNTIME_PID_LOOKUP_UNAVAILABLE)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"


def test_list_runs_marks_stalled_running_process_as_failed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stalled\n", encoding="utf-8")
    old_age = datetime.now().timestamp() - 950
    os.utime(process_log, (old_age, old_age))

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]


def test_list_runs_marks_processing_queue_stall_failed_even_if_crawler_files_keep_changing(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("consume-test stalled\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    (engagement_dir / "scans").mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(scope_path, (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('processing')")
        connection.commit()

    noisy_crawler_file = engagement_dir / "scans" / "katana_output.jsonl"
    noisy_crawler_file.write_text('{"url":"https://example.com/health"}\n', encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"


def test_list_runs_marks_pending_queue_stall_failed_even_if_only_exploit_artifacts_keep_changing(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("exploit dispatched\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    (engagement_dir / "scans" / "exploit-validation").mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("stale queue\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("pending",), ("pending",), ("done",)],
        )
        connection.commit()

    noisy_exploit_file = engagement_dir / "scans" / "exploit-validation" / "probe.body"
    noisy_exploit_file.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert "pending queue items remained undispatched" in metadata["stop_reason_text"]


def test_list_runs_marks_corrupt_cases_db_failed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("consume-test still working\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("processing",), ("done",)],
        )
        connection.commit()

    real_connect = sqlite3.connect
    cases_db = engagement_dir / "cases.db"

    class FaultyQueueConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            query = str(sql)
            if str(self._connection.execute("PRAGMA database_list").fetchone()[2]) == str(cases_db) and query == "SELECT COUNT(*) FROM cases WHERE status = 'processing'":
                raise sqlite3.DatabaseError("database disk image is malformed")
            return self._connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._connection.__exit__(exc_type, exc, tb)

    def flaky_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        database_str = str(database)
        if database_str == str(cases_db) or database_str == f"file:{cases_db}?mode=ro":
            return FaultyQueueConnection(connection)
        return connection

    monkeypatch.setattr("app.services.runs.sqlite3.connect", flaky_connect)
    monkeypatch.setattr("app.services.runs._read_sqlite_snapshot", lambda _path, _reader, default: default)
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "cases_db_corrupt"
    assert "queue state could not be trusted" in metadata["stop_reason_text"]


def test_list_runs_keeps_running_when_readwrite_cases_db_looks_corrupt_but_readonly_fallback_succeeds(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("consume-test still working\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("processing",), ("done",)],
        )
        connection.commit()

    real_connect = sqlite3.connect
    cases_db = engagement_dir / "cases.db"

    class FaultyReadWriteConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            query = str(sql)
            if str(self._connection.execute("PRAGMA database_list").fetchone()[2]) == str(cases_db) and query == "SELECT COUNT(*) FROM cases WHERE status = 'processing'":
                raise sqlite3.DatabaseError("database disk image is malformed")
            return self._connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._connection.__exit__(exc_type, exc, tb)

    def flaky_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        if str(database) == str(cases_db) and not kwargs.get("uri", False):
            return FaultyReadWriteConnection(connection)
        return connection

    monkeypatch.setattr("app.services.runs.sqlite3.connect", flaky_connect)
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert stopped == []
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata.get("stop_reason_code") is None


def test_list_runs_marks_stalled_run_failed_even_if_cases_sqlite_wal_churns(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("exploit dispatched\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "exploit",
                "phases_completed": ["recon", "collect", "consume_test"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("stale exploit\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    recent_wal = engagement_dir / "cases.db-wal"
    recent_wal.write_text("optimizer read churn\n", encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_list_runs_ignores_replayed_process_log_mtime_when_json_timestamps_are_stale(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    stale_timestamp_ms = int((datetime.now().timestamp() - 950) * 1000)
    process_log.write_text(
        json.dumps({"type": "step_start", "timestamp": stale_timestamp_ms, "sessionID": "ses_old"}) + "\n",
        encoding="utf-8",
    )
    process_log.touch()

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "exploit",
                "phases_completed": ["recon", "collect", "consume_test"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    old_epoch = datetime.now().timestamp() - 950
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("stale exploit\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_list_runs_ignores_replayed_opencode_log_mtime_when_text_timestamps_are_stale(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale runtime output\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))

    opencode_log = run_root / "opencode-home" / "log" / "2026-03-30T000000.log"
    opencode_log.parent.mkdir(parents=True, exist_ok=True)
    opencode_log.write_text(
        "INFO  2026-03-29T20:14:17 +0ms service=session.processor process\n",
        encoding="utf-8",
    )
    opencode_log.touch()

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "exploit",
                "phases_completed": ["recon", "collect", "consume_test"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    old_epoch = datetime.now().timestamp() - 950
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("stale exploit\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_list_runs_ignores_recent_heartbeat_events_when_detecting_queue_stalls(monkeypatch):
    from app.db import database_path

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    old_epoch = datetime.now().timestamp() - 950
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("stale consume-test\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(status, assigned_agent, source) VALUES ('processing', 'vulnerability-analyst', 'katana')"
        )
        connection.commit()

    heartbeat_at = datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "INSERT INTO events(run_id, event_type, phase, task_name, agent_name, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], "run.heartbeat", "consume-test", "runtime", "launcher", "still waiting", heartbeat_at),
        )
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE id = ?",
            (heartbeat_at, run["id"]),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert "stall timeout elapsed" in metadata["stop_reason_text"]



def test_list_runs_keeps_recent_opencode_log_activity_running(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("exploit dispatched\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "exploit",
                "phases_completed": ["recon", "collect", "consume_test"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    opencode_log = run_root / "opencode-home" / "log" / "2026-03-28T000000.log"
    opencode_log.parent.mkdir(parents=True, exist_ok=True)
    opencode_log.write_text('{"type":"message","text":"still working"}\n', encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert stopped == []


def test_list_runs_keeps_processing_queue_under_15_minute_watchdog_running(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("consume-test still working\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 700
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    (engagement_dir / "scans").mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(scope_path, (old_epoch, old_epoch))
    (engagement_dir / "log.md").write_text("processing queue\n", encoding="utf-8")
    os.utime(engagement_dir / "log.md", (old_epoch, old_epoch))
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('processing')")
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert stopped == []


def test_list_runs_revives_live_failed_run(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "failed")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("still active\n", encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"


def test_list_runs_reconciles_incomplete_completed_run_to_failed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    db.update_run_status(run["id"], "completed")
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "incomplete_terminal_state"
    assert metadata["stop_reason_text"] == "Engagement status is in_progress."


def test_list_runs_marks_missing_runtime_supervisor_with_explicit_stop_reason(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = datetime('now', '-700 seconds') WHERE id = ?",
            (run["id"],),
        )
        connection.commit()
    old_epoch = datetime.now().timestamp() - 700
    os.utime(run_root / "run.json", (old_epoch, old_epoch))

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "runtime_disappeared"
    assert "Runtime supervisor disappeared" in metadata["stop_reason_text"]


def test_list_runs_auto_resumes_incomplete_run_when_runtime_supervisor_is_missing(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-29-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-29-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("pending",), ("done",)],
        )
        connection.commit()

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = datetime('now', '-700 seconds') WHERE id = ?",
            (run["id"],),
        )
        connection.commit()
    old_epoch = datetime.now().timestamp() - 700
    os.utime(run_root / "run.json", (old_epoch, old_epoch))

    captured: dict[str, str] = {}

    def fake_auto_resume(project_obj, run_obj, user_obj, *, phase, reason_code, reason_text):
        captured["phase"] = phase
        captured["reason_code"] = reason_code
        captured["reason_text"] = reason_text
        return True

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)
    monkeypatch.setattr("app.services.runs._maybe_auto_resume_run", fake_auto_resume)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert captured == {
        "phase": "consume-test",
        "reason_code": "runtime_disappeared",
        "reason_text": "Runtime supervisor disappeared before the engagement reached a terminal state.",
    }



def test_list_runs_auto_resumes_logged_incomplete_stop_when_runtime_supervisor_is_missing(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-29-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-29-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text(
        "# Activity Log\n\n"
        "## [01:01] Run stop — operator\n\n"
        "**Action**: stop_reason=queue_incomplete\n"
        "**Result**: pending queue remains and the current session is pausing before exhausting all consume-test work\n",
        encoding="utf-8",
    )

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = datetime('now', '-700 seconds') WHERE id = ?",
            (run["id"],),
        )
        connection.commit()
    old_epoch = datetime.now().timestamp() - 700
    os.utime(run_root / "run.json", (old_epoch, old_epoch))

    captured: dict[str, str] = {}

    def fake_auto_resume(project_obj, run_obj, user_obj, *, phase, reason_code, reason_text):
        captured["phase"] = phase
        captured["reason_code"] = reason_code
        captured["reason_text"] = reason_text
        return True

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)
    monkeypatch.setattr("app.services.runs._maybe_auto_resume_run", fake_auto_resume)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert captured == {
        "phase": "consume-test",
        "reason_code": "queue_incomplete",
        "reason_text": "pending queue remains and the current session is pausing before exhausting all consume-test work",
    }


def test_list_runs_marks_completed_scope_as_completed_even_if_runtime_is_still_alive(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "current_phase": "complete",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text(
        json.dumps({"surface_type": "api_documentation", "target": "GET /api-docs/", "status": "covered"}) + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "completed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["stop_reason_text"] == "Run completed successfully."
    assert stopped == [run["id"]]


def test_list_runs_marks_completed_scope_alias_as_completed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example-alias"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example-alias\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "current_phase": "complete",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text(
        json.dumps({"surface_type": "api_documentation", "target": "GET /api-docs/", "status": "covered"}) + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "completed"
    normalized = json.loads(scope_path.read_text(encoding="utf-8"))
    assert normalized["status"] == "complete"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["stop_reason_text"] == "Run completed successfully."
    assert stopped == [run["id"]]


def test_list_runs_marks_completed_scope_as_completed_when_runtime_has_already_exited(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example-exited"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example-exited\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "current_phase": "complete",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text(
        json.dumps({"surface_type": "api_documentation", "target": "GET /api-docs/", "status": "covered"}) + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "completed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["stop_reason_text"] == "Run completed successfully."


def test_list_runs_rewrites_stale_terminal_reason_when_completed_scope_is_already_final(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "completed")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example-final"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example-final\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "current_phase": "complete",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text(
        json.dumps({"surface_type": "api_documentation", "target": "GET /api-docs/", "status": "covered"}) + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    metadata_path = run_root / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["stop_reason_code"] = "runtime_disappeared"
    metadata["stop_reason_text"] = "Runtime supervisor disappeared before the engagement reached a terminal state."
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "completed"
    refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert refreshed["stop_reason_code"] == "completed"
    assert refreshed["stop_reason_text"] == "Run completed successfully."


def test_list_runs_normalizes_scope_phase_aliases(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "test",
                "phases_completed": ["recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    normalized = json.loads(scope_path.read_text(encoding="utf-8"))
    assert normalized["current_phase"] == "consume_test"


def test_list_runs_keeps_running_when_queue_query_hits_transient_lock_and_readonly_fallback_succeeds(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("collect still working\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example-lock"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example-lock\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "collect",
                "phases_completed": ["recon"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases_db = engagement_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("pending",), ("processing",), ("done",)],
        )
        connection.commit()

    real_connect = sqlite3.connect

    class LockedProcessingConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            if str(sql) == "SELECT COUNT(*) FROM cases WHERE status = 'processing'":
                raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._connection.__exit__(exc_type, exc, tb)

    def flaky_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        if str(database) == str(cases_db) and not kwargs.get("uri", False):
            return LockedProcessingConnection(connection)
        return connection

    monkeypatch.setattr("app.services.runs.sqlite3.connect", flaky_connect)
    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"
    assert stopped == []



def test_list_runs_marks_early_recon_stall_failed_even_if_pid_is_alive(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stalled recon\n", encoding="utf-8")
    old_epoch = 1742860800
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-28-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-28-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "recon",
                "phases_completed": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: 12345)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"


def test_delete_run_removes_runtime_files_and_db_records():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://example.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.json").write_text(
        json.dumps({"pid": 999999, "command": "opencode run", "started_at": "2026-03-25T00:00:00Z"}),
        encoding="utf-8",
    )
    db.create_event(run["id"], "run.started", "unknown", "runtime", "launcher", "started")

    response = client.request(
        "DELETE",
        f"/projects/{project['id']}/runs/{run['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    assert not run_root.exists()
    assert db.get_run_by_id(run["id"]) is None
    assert db.list_events_for_run(run["id"]) == []
