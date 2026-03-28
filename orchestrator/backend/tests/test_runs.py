import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime

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
    old_age = datetime.now().timestamp() - 240
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
    old_epoch = datetime.now().timestamp() - 700
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


def test_list_runs_keeps_early_recon_stall_running_while_pid_is_alive(monkeypatch):
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

    runs_response = client.get(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["status"] == "running"


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
