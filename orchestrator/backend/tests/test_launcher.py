import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sqlite3

from fastapi.testclient import TestClient

from app import db
from app.config import settings
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


def test_create_run_prepares_isolated_runtime_directories():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    run_root = Path(run["engagement_root"])
    assert run_root.exists()
    assert (run_root / "runtime").is_dir()
    assert (run_root / "workspace").is_dir()
    assert (run_root / "opencode-home").is_dir()

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["id"] == run["id"]
    assert metadata["run_id"] == run["id"]
    assert metadata["target"] == "https://example.com"
    assert metadata["engagement_root"] == run["engagement_root"]
    assert metadata["created_at"] == run["created_at"]
    assert metadata["updated_at"] == run["updated_at"]


def test_prepare_run_runtime_syncs_agent_source_into_workspace():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])

    run_root = Path(run["engagement_root"])
    source_engage = Path(settings.agent_source_dir) / ".opencode" / "commands" / "engage.md"
    workspace_engage = run_root / "workspace" / ".opencode" / "commands" / "engage.md"

    assert workspace_engage.exists()
    assert workspace_engage.read_text(encoding="utf-8") == source_engage.read_text(encoding="utf-8")
    assert not (run_root / "workspace" / "engagements").exists()


def test_each_run_gets_its_own_runtime_root():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    first_run = create_run(client, token, project["id"], "https://one.example")
    second_run = create_run(client, token, project["id"], "https://two.example")

    assert first_run["engagement_root"] != second_run["engagement_root"]
    assert Path(first_run["engagement_root"], "run.json").exists()
    assert Path(second_run["engagement_root"], "run.json").exists()


def test_create_run_can_auto_launch_when_enabled(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    assert run["status"] == "running"
    assert Path(run["engagement_root"], "runtime", "process.log").exists()


def test_launch_runtime_container_uses_docker_init(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://init-check.example")

    from app.services.launcher import _launch_runtime_container

    started_commands = []

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["docker", "run", "-d"]:
            started_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher._spawn_runtime_log_follower", lambda *_args, **_kwargs: FakeLogFollower())

    project_obj = db.get_project_by_id(project["id"])
    user_obj = db.get_user_by_username("alice")
    run_obj = db.get_run_by_id(run["id"])
    assert project_obj is not None
    assert user_obj is not None
    assert run_obj is not None

    runtime_log = Path(run["engagement_root"]) / "runtime" / "process.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    with runtime_log.open("ab") as log_handle:
        _launch_runtime_container(project_obj, run_obj, user_obj, command_text="/autoengage https://init-check.example", log_handle=log_handle)

    assert started_commands
    assert "--init" in started_commands[0]


def test_locate_runtime_pid_treats_running_container_without_matching_launcher_pid_as_live_runtime(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://orphaned.example")

    metadata_path = Path(run["engagement_root"]) / "runtime" / "process.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
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

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")

    from app.services.launcher import locate_runtime_pid

    assert locate_runtime_pid(db.get_run_by_id(run["id"])) == -1



def test_auto_launch_emits_runtime_heartbeat_when_process_is_still_running(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            process_log = Path(self._args[0].engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", "exited"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(statuses)}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout="0\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    events = db.list_events_for_run(run["id"])
    assert any(event.event_type == "run.heartbeat" for event in events)
    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "incomplete_stop"
    assert "No active engagement directory found." == metadata["stop_reason_text"]


def test_heartbeat_context_prefers_newer_run_metadata_phase_over_stale_scope_phase():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://phase-lag.example")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-phase-lag"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-phase-lag\n",
        encoding="utf-8",
    )

    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
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

    metadata_path = run_root / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["current_phase"] = "exploit"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    import os
    from app.services.launcher import _heartbeat_context

    old_epoch = datetime.now().timestamp() - 10
    new_epoch = datetime.now().timestamp()
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(metadata_path, (new_epoch, new_epoch))

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    phase, summary = _heartbeat_context(run_row)
    assert phase == "exploit"
    assert summary == "Runtime active in exploit; waiting for new agent output."



def test_heartbeat_context_prefers_newer_scope_phase_over_stale_run_metadata():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://phase-lag-scope.example")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000001-phase-lag"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000001-phase-lag\n",
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

    metadata_path = run_root / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["current_phase"] = "exploit"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    import os
    from app.services.launcher import _heartbeat_context

    old_epoch = datetime.now().timestamp() - 10
    new_epoch = datetime.now().timestamp()
    os.utime(metadata_path, (old_epoch, old_epoch))
    os.utime(scope_path, (new_epoch, new_epoch))

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    phase, summary = _heartbeat_context(run_row)
    assert phase == "consume_test"
    assert summary == "Runtime active in consume_test; waiting for new agent output."


def test_normalize_scope_file_deduplicates_completed_phases_in_order():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://dedupe.example")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000002-dedupe"
    engagement_dir.mkdir(parents=True, exist_ok=True)

    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect", "consume_test", "recon", "collect"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from app.services.launcher import _normalize_scope_file

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    normalized = _normalize_scope_file(scope_path, run=run_row)
    assert normalized is not None
    assert normalized["phases_completed"] == ["recon", "collect", "consume_test"]

    persisted = json.loads(scope_path.read_text(encoding="utf-8"))
    assert persisted["phases_completed"] == ["recon", "collect", "consume_test"]



def test_supervise_container_stops_live_stalled_runtime(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://stalled.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None
    project_row = db.get_project_by_id(project["id"])
    assert project_row is not None
    user_row = db.get_user_by_id(project_row.user_id)
    assert user_row is not None

    run_root = Path(run["engagement_root"])
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text("stalled after llm stream\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 950
    process_log.touch()
    import os
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-stalled"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-stalled\n",
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

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")
    monkeypatch.setattr("app.services.launcher._maybe_auto_resume_run", lambda *args, **kwargs: False)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.launcher.stop_run_runtime", lambda stalled_run: stopped.append(stalled_run.id))

    from app.services.launcher import _supervise_container

    _supervise_container(
        run_row,
        project_row,
        user_row,
        f"redteam-orch-run-{run['id']:04d}",
        None,
        io.BytesIO(),
        heartbeat_interval=0,
    )

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_running_container_stall_reason_keeps_early_collect_alive_when_rw_cases_db_is_locked_but_readonly_fallback_succeeds(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://collect-lock.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text("collect still working\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 200
    import os
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-collect-lock"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-collect-lock\n",
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

    monkeypatch.setattr("app.services.launcher.sqlite3.connect", flaky_connect)

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_ignores_fresh_process_metadata_mtime():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://stalled-runtime.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stalled after model call\n", encoding="utf-8")
    process_metadata = runtime_dir / "process.json"
    process_metadata.write_text(
        json.dumps({"run_id": run["id"], "container_name": f"redteam-orch-run-{run['id']:04d}"}) + "\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-stalled-runtime"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-stalled-runtime\n",
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
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    old_epoch = datetime.now().timestamp() - 950
    import os
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "exploit",
        "queue_stalled",
        "Runtime produced no new output before stall timeout elapsed.",
    )



def test_running_container_stall_reason_flags_processing_agent_without_matching_active_runtime_agent():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://orphaned-processing.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent queue fetch without dispatch\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-orphaned-processing"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-orphaned-processing\n",
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
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(status, assigned_agent) VALUES ('processing', 'vulnerability-analyst')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "exploit-developer", "status": "active"},
                    {"agent_name": "source-analyzer", "status": "active"},
                    {"agent_name": "vulnerability-analyst", "status": "completed"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Processing queue assignments (vulnerability-analyst) had no matching active runtime agent after stall grace period elapsed (active agents: exploit-developer, source-analyzer).",
    )



def test_running_container_stall_reason_keeps_processing_case_alive_when_active_runtime_agent_matches():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://matched-processing.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent queue fetch with matching dispatch\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-matched-processing"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-matched-processing\n",
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
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(status, assigned_agent) VALUES ('processing', 'vulnerability-analyst')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "vulnerability-analyst", "status": "active"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_keeps_early_recon_alive_when_workflow_activity_is_recent():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://recent-recon.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text("recon started\n", encoding="utf-8")
    old_epoch = datetime.now().timestamp() - 240
    import os
    os.utime(process_log, (old_epoch, old_epoch))

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-recent-recon"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-recent-recon\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
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
    recent_epoch = datetime.now().timestamp() - 15
    os.utime(scope_path, (recent_epoch, recent_epoch))
    log_path = engagement_dir / "log.md"
    log_path.write_text("recent source analysis summary\n", encoding="utf-8")
    os.utime(log_path, (recent_epoch, recent_epoch))

    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.commit()

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_supervise_container_ignores_replayed_process_log_mtime_when_json_timestamps_are_stale(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://stalled-replay.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None
    project_row = db.get_project_by_id(project["id"])
    assert project_row is not None
    user_row = db.get_user_by_id(project_row.user_id)
    assert user_row is not None

    run_root = Path(run["engagement_root"])
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    stale_timestamp_ms = int((datetime.now().timestamp() - 950) * 1000)
    process_log.write_text(
        json.dumps({"type": "step_start", "timestamp": stale_timestamp_ms, "sessionID": "ses_old"}) + "\n",
        encoding="utf-8",
    )
    process_log.touch()

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-stalled-replay"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-stalled-replay\n",
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

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")
    monkeypatch.setattr("app.services.launcher._maybe_auto_resume_run", lambda *args, **kwargs: False)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.launcher.stop_run_runtime", lambda stalled_run: stopped.append(stalled_run.id))

    from app.services.launcher import _supervise_container

    _supervise_container(
        run_row,
        project_row,
        user_row,
        f"redteam-orch-run-{run['id']:04d}",
        None,
        io.BytesIO(),
        heartbeat_interval=0,
    )

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_supervise_container_ignores_replayed_opencode_log_mtime_when_text_timestamps_are_stale(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://stalled-opencode-replay.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None
    project_row = db.get_project_by_id(project["id"])
    assert project_row is not None
    user_row = db.get_user_by_id(project_row.user_id)
    assert user_row is not None

    run_root = Path(run["engagement_root"])
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text("stale runtime output\n", encoding="utf-8")
    import os
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
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-stalled-opencode-replay"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-stalled-opencode-replay\n",
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

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")
    monkeypatch.setattr("app.services.launcher._maybe_auto_resume_run", lambda *args, **kwargs: False)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.launcher.stop_run_runtime", lambda stalled_run: stopped.append(stalled_run.id))

    from app.services.launcher import _supervise_container

    _supervise_container(
        run_row,
        project_row,
        user_row,
        f"redteam-orch-run-{run['id']:04d}",
        None,
        io.BytesIO(),
        heartbeat_interval=0,
    )

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"
    assert stopped == [run["id"]]
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_stalled"
    assert metadata["stop_reason_text"] == "Runtime produced no new output before stall timeout elapsed."


def test_auto_launch_missing_container_uses_incomplete_queue_artifacts(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
            engagement_dir = workspace / "engagements" / "2026-03-29-000000-example-queue"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-29-000000-example-queue\n",
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
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", None])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            status = next(statuses)
            if status is None:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="Error: No such object\n")
            return subprocess.CompletedProcess(command, 0, stdout=f"{status}\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    monkeypatch.setattr("app.services.launcher._AUTO_RESUME_LIMIT", 0)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "queue_incomplete"
    assert metadata["stop_reason_text"] == "Queue still has pending=1 processing=0."



def test_auto_launch_auto_resumes_incomplete_exit(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    attempt = {"count": 0}
    launched_commands: list[list[str]] = []

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            attempt["count"] += 1
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
            engagement_dir = workspace / "engagements" / "2026-03-29-000000-example-resume"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-29-000000-example-resume\n",
                encoding="utf-8",
            )
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            cases_db = engagement_dir / "cases.db"
            if cases_db.exists():
                cases_db.unlink()
            with sqlite3.connect(cases_db) as connection:
                connection.execute(
                    "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
                )
                if attempt["count"] == 1:
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
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("pending",), ("done",)],
                    )
                else:
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
                    (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
                    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("done",), ("error",)],
                    )
                connection.commit()
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", "exited", "running", "exited"])
    exit_codes = iter(["0", "0"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            launched_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(statuses)}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(exit_codes)}\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    assert len(launched_commands) == 2
    assert any("/resume" in " ".join(command) for command in launched_commands[1:])
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["auto_resume_count"] == 1
    events = db.list_events_for_run(run["id"])
    assert any(event.event_type == "run.resumed" for event in events)



def test_auto_launch_missing_container_auto_resumes_incomplete_runtime(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    attempt = {"count": 0}
    launched_commands: list[list[str]] = []

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            attempt["count"] += 1
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
            engagement_dir = workspace / "engagements" / "2026-03-29-000000-example-disappeared"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-29-000000-example-disappeared\n",
                encoding="utf-8",
            )
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            cases_db = engagement_dir / "cases.db"
            if cases_db.exists():
                cases_db.unlink()
            with sqlite3.connect(cases_db) as connection:
                connection.execute(
                    "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
                )
                if attempt["count"] == 1:
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
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("pending",), ("done",)],
                    )
                else:
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
                    (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
                    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("done",), ("error",)],
                    )
                connection.commit()
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", None, "running", "exited"])
    exit_codes = iter(["0"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            launched_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            status = next(statuses)
            if status is None:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="Error: No such object\n")
            return subprocess.CompletedProcess(command, 0, stdout=f"{status}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(exit_codes)}\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    assert len(launched_commands) == 2
    assert any("/resume" in " ".join(command) for command in launched_commands[1:])
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["auto_resume_count"] == 1
    events = db.list_events_for_run(run["id"])
    assert any(event.event_type == "run.resumed" for event in events)



def test_auto_launch_missing_container_preserves_completed_artifacts(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
            engagement_dir = workspace / "engagements" / "2026-03-29-000000-example-complete"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-29-000000-example-complete\n",
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
            (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
            (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
            with sqlite3.connect(engagement_dir / "cases.db") as connection:
                connection.execute(
                    "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
                )
                connection.executemany(
                    "INSERT INTO cases(status) VALUES (?)",
                    [("done",), ("error",)],
                )
                connection.commit()
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", None])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            status = next(statuses)
            if status is None:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="Error: No such object\n")
            return subprocess.CompletedProcess(command, 0, stdout=f"{status}\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["stop_reason_text"] == "Run completed successfully."



def test_engagement_completion_state_prefers_logged_stop_reason():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")

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
                "current_phase": "recon",
                "phases_completed": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text(
        "# Activity Log\n\n"
        "## [13:52] Run stop — operator\n\n"
        "**Action**: stop_reason=runtime_error\n"
        "**Result**: target http://127.0.0.1:8000 was not listening; recon and source collection could not proceed\n",
        encoding="utf-8",
    )

    from app import db as app_db
    from app.services.launcher import engagement_completion_state

    app_db.update_run_status(run["id"], "failed")
    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None

    assert engagement_completion_state(latest) == (
        False,
        "target http://127.0.0.1:8000 was not listening; recon and source collection could not proceed",
    )


def test_engagement_completion_state_accepts_completed_status_alias():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://example.com")

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
                "status": "completed",
                "current_phase": "complete",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    from app import db as app_db
    from app.services.launcher import engagement_completion_state

    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None
    assert engagement_completion_state(latest) == (True, "Engagement completed and finalized.")

    normalized = json.loads((engagement_dir / "scope.json").read_text(encoding="utf-8"))
    assert normalized["status"] == "complete"


def test_normalize_active_scope_marks_completed_report_and_log_headers(monkeypatch):
    import os
    import time

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://example.com")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-example\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "current_phase": "complete",
                "start_time": "2026-03-29T23:59:38Z",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text(
        "# Engagement Log\n\n"
        "- **Target**: https://example.com\n"
        "- **Date**: 2026-03-29\n"
        "- **Status**: In Progress\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text(
        "# Penetration Test Report: https://example.com\n"
        "**Date**: 2026-03-29 — In Progress\n"
        "**Target**: https://example.com  **Scope**: example.com, *.example.com  **Status**: In Progress\n",
        encoding="utf-8",
    )
    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("error",)],
        )
        connection.commit()

    from app import db as app_db
    from app.services.launcher import normalize_active_scope

    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None

    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Asia/Singapore")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        normalize_active_scope(latest)
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        if hasattr(time, "tzset"):
            time.tzset()

    log_text = (engagement_dir / "log.md").read_text(encoding="utf-8")
    report_text = (engagement_dir / "report.md").read_text(encoding="utf-8")

    assert "- **Status**: Completed" in log_text
    assert "**Date**: 2026-03-30 — Completed" in report_text
    assert "**Status**: Completed" in report_text


def test_auto_launch_marks_completed_only_when_engagement_is_finalized(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
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
            (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
            (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
            with sqlite3.connect(engagement_dir / "cases.db") as connection:
                connection.execute(
                    "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
                )
                connection.commit()
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", "exited"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(statuses)}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout="0\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://launched.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["stop_reason_text"] == "Run completed successfully."


def test_auto_launch_injects_project_model_and_provider_env(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Configured",
            "provider_id": "openai",
            "model_id": "gpt-5.4",
            "small_model_id": "gpt-5.4-mini",
            "api_key": "sk-live-test",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()

    captured: dict[str, list[str]] = {}

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://configured.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    assert run["status"] == "running"
    command = captured["command"]
    joined = " ".join(command)
    assert "REDTEAM_OPENCODE_MODEL=openai/gpt-5.4" in joined
    assert "REDTEAM_OPENCODE_SMALL_MODEL=openai/gpt-5.4-mini" in joined
    assert "OPENAI_API_KEY=sk-live-test" in joined
    assert "OPENAI_BASE_URL=https://api.openai.com/v1" in joined
    assert "OPENAI_MODEL=gpt-5.4" in joined


def test_start_run_runtime_rewrites_loopback_target_for_container_command(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    captured: dict[str, list[str]] = {}

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    assert run["status"] == "running"
    command = captured["command"]
    joined = " ".join(command)
    assert "/autoengage http://host.docker.internal:8000" in joined
    assert "/autoengage http://127.0.0.1:8000" not in joined

    metadata = json.loads(Path(run["engagement_root"], "run.json").read_text(encoding="utf-8"))
    assert metadata["target"] == "http://127.0.0.1:8000"



def test_process_metadata_redacts_sensitive_env(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Redacted",
            "provider_id": "openai",
            "model_id": "gpt-5.4",
            "api_key": "sk-live-secret",
            "auth_json": '{"headers":{"Authorization":"Bearer auth-secret"}}',
            "env_json": '{"CAPTCHA_SOLVER_KEY":"solver-secret"}',
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://redacted.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    process_metadata = json.loads(Path(run["engagement_root"], "runtime", "process.json").read_text(encoding="utf-8"))
    joined = " ".join(process_metadata["command"])
    assert "OPENAI_API_KEY=<redacted>" in joined
    assert "sk-live-secret" not in joined


def test_prepare_run_runtime_writes_auth_seed_and_env_seed():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Seeded",
            "auth_json": '{"headers":{"Authorization":"Bearer abc"}}',
            "env_json": '{"HTTP_PROXY":"http://proxy:8080"}',
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()

    run = create_run(client, token, project["id"], "https://seeded.example")
    run_root = Path(run["engagement_root"])
    assert json.loads((run_root / "seed" / "auth.json").read_text(encoding="utf-8"))["headers"]["Authorization"] == "Bearer abc"
    assert json.loads((run_root / "seed" / "env.json").read_text(encoding="utf-8"))["HTTP_PROXY"] == "http://proxy:8080"


def test_init_only_zero_exit_is_marked_failed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            process_log = Path(self._args[0].engagement_root) / "runtime" / "process.log"
            process_log.write_text("init only\n", encoding="utf-8")
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["exited"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(statuses)}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout="0\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://init-only.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "failed"


def test_start_run_runtime_clears_stale_terminal_reason(monkeypatch):
    from app.services import launcher

    client = TestClient(app)
    token = register_and_login(client, "alice-clear-stop-reason")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://clear-stop-reason.example")

    run_model = db.get_run_by_id(run["id"])
    project_model = db.get_project_by_id(project["id"])
    user_model = db.get_user_by_username("alice-clear-stop-reason")
    assert run_model is not None
    assert project_model is not None
    assert user_model is not None

    metadata_path = Path(run["engagement_root"]) / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["stop_reason_code"] = "queue_stalled"
    metadata["stop_reason_text"] = "Runtime produced no new output before stall timeout elapsed."
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    class FakeLogFollower:
        def poll(self):
            return 0

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))

    started = launcher.start_run_runtime(project_model, run_model, user_model)
    assert started.status == "running"

    refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "stop_reason_code" not in refreshed
    assert "stop_reason_text" not in refreshed
    assert "ended_at" not in refreshed


def test_ensure_runtime_log_follower_restarts_dead_follower(monkeypatch):
    from app.services.launcher import _ensure_runtime_log_follower

    client = TestClient(app)
    token = register_and_login(client, "alice-log-follower")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://log-follower.example")

    run_model = db.get_run_by_id(run["id"])
    assert run_model is not None

    started_commands: list[list[str]] = []

    class DeadFollower:
        def poll(self):
            return 1

    class LiveFollower:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        started_commands.append(command)
        return LiveFollower()

    monkeypatch.setattr("app.services.launcher.subprocess.Popen", fake_popen)

    follower = _ensure_runtime_log_follower(run_model, DeadFollower(), io.BytesIO())
    assert follower is not None
    assert follower.poll() is None
    assert started_commands == [["docker", "logs", "-f", f"redteam-orch-run-{run['id']:04d}"]]


def test_runtime_log_follow_command_resumes_from_last_captured_activity(tmp_path):
    from app.services.launcher import _runtime_log_follow_command, process_log_path_for

    client = TestClient(app)
    token = register_and_login(client, "alice-log-follow-resume")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://resume-log.example")

    run_model = db.get_run_by_id(run["id"])
    assert run_model is not None

    process_log = process_log_path_for(run_model)
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        '{"timestamp": 1774866503642, "type": "tool_use"}\n',
        encoding="utf-8",
    )

    command = _runtime_log_follow_command(run_model)

    assert command[:4] == ["docker", "logs", "-f", "--since"]
    assert command[4] == "2026-03-30T10:28:23.643Z"
    assert command[5] == f"redteam-orch-run-{run['id']:04d}"


def test_supervise_container_drains_runtime_log_follower_before_terminal_state(monkeypatch):
    from app.services.launcher import _supervise_container, process_log_path_for

    client = TestClient(app)
    token = register_and_login(client, "alice-log-drain")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://drain-log.example")

    run_model = db.get_run_by_id(run["id"])
    project_model = db.get_project_by_id(project["id"])
    user_model = db.get_user_by_username("alice-log-drain")
    assert run_model is not None
    assert project_model is not None
    assert user_model is not None

    workspace = Path(run["engagement_root"]) / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000000-drain-log-example"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000000-drain-log-example\n",
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
    (engagement_dir / "log.md").write_text("# Log\n- **Status**: Completed\n", encoding="utf-8")
    (engagement_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)")
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    process_log = process_log_path_for(run_model)
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text('{"type":"tool_use","part":{"tool":"todowrite","state":{"input":{}}}}\n', encoding="utf-8")

    class SlowFollower:
        def __init__(self):
            self.wait_calls = 0
            self._done = False
            self.terminated = False
            self.killed = False

        def poll(self):
            return 0 if self._done else None

        def wait(self, timeout=None):
            self.wait_calls += 1
            with process_log.open("a", encoding="utf-8") as handle:
                handle.write('{"timestamp":1774887570000,"type":"tool_use","part":{"tool":"task","agent":"report-writer","state":{"status":"completed"}}}\n')
            self._done = True
            return 0

        def terminate(self):
            self.terminated = True
            self._done = True

        def kill(self):
            self.killed = True
            self._done = True

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "exited")
    monkeypatch.setattr("app.services.launcher._container_exit_code", lambda _name: 0)

    follower = SlowFollower()
    with process_log.open("ab") as log_handle:
        _supervise_container(run_model, project_model, user_model, "container-123", follower, log_handle)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    assert follower.wait_calls == 1
    log_text = process_log.read_text(encoding="utf-8")
    assert '"report-writer"' in log_text
    assert not follower.terminated
    assert not follower.killed


def test_auto_launch_allows_third_resume_attempt(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice-third-resume")
    project = create_project(client, token)

    attempt = {"count": 0}
    launched_commands: list[list[str]] = []

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            attempt["count"] += 1
            run = self._args[0]
            workspace = Path(run.engagement_root) / "workspace"
            engagement_dir = workspace / "engagements" / "2026-03-30-000000-example-third-resume"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-30-000000-example-third-resume\n",
                encoding="utf-8",
            )
            process_log = Path(run.engagement_root) / "runtime" / "process.log"
            process_log.write_text(
                json.dumps({"type": "tool_use", "part": {"tool": "todowrite", "state": {"input": {}}}}) + "\n",
                encoding="utf-8",
            )
            cases_db = engagement_dir / "cases.db"
            if cases_db.exists():
                cases_db.unlink()
            with sqlite3.connect(cases_db) as connection:
                connection.execute(
                    "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
                )
                if attempt["count"] < 3:
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
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("pending",), ("done",)],
                    )
                else:
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
                    (engagement_dir / "report.md").write_text("# report\n", encoding="utf-8")
                    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
                    connection.executemany(
                        "INSERT INTO cases(status) VALUES (?)",
                        [("done",), ("error",)],
                    )
                connection.commit()
            self._target(*self._args)

    class FakeLogFollower:
        def poll(self):
            return 0

    statuses = iter(["running", "exited", "running", "exited", "running", "exited"])
    exit_codes = iter(["0", "0", "0"])

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            launched_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(statuses)}\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.ExitCode}}"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{next(exit_codes)}\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    object.__setattr__(settings, "auto_launch_runs", True)

    try:
        run = create_run(client, token, project["id"], "https://third-resume.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    assert len(launched_commands) == 3
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed"
    assert metadata["auto_resume_count"] == 2
    events = db.list_events_for_run(run["id"])
    assert len([event for event in events if event.event_type == "run.resumed"]) == 2
