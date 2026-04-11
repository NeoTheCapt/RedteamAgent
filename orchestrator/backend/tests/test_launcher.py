import io
import json
from datetime import UTC, datetime, timedelta
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



def test_locate_runtime_pid_ignores_docker_log_followers_when_container_is_gone(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://missing-runtime.example")

    container_name = f"redteam-orch-run-{run['id']:04d}"
    metadata_path = Path(run["engagement_root"]) / "runtime" / "process.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "run_id": run["id"],
                "container_name": container_name,
                "launcher_pid": 999999,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: None)
    monkeypatch.setattr(
        "app.services.launcher.subprocess.check_output",
        lambda *_args, **_kwargs: (
            f"12345 docker logs -f --since 2026-03-31T19:17:32.621Z {container_name} ORCHESTRATOR_RUN_ID={run['id']}"
        ),
    )

    from app.services.launcher import locate_runtime_pid

    assert locate_runtime_pid(db.get_run_by_id(run["id"])) is None



def test_stop_run_runtime_terminates_orphaned_runtime_log_followers(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://cleanup.example")

    container_name = f"redteam-orch-run-{run['id']:04d}"
    metadata_path = Path(run["engagement_root"]) / "runtime" / "process.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "run_id": run["id"],
                "container_name": container_name,
                "launcher_pid": 999999,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    removed_commands: list[list[str]] = []
    killed_pids: list[int] = []

    def fake_run(command, **kwargs):
        removed_commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr(
        "app.services.launcher.subprocess.check_output",
        lambda *_args, **_kwargs: (
            f"12345 docker logs -f --since 2026-03-31T19:17:32.621Z {container_name} ORCHESTRATOR_RUN_ID={run['id']}\n"
            "54321 /usr/bin/other-process"
        ),
    )
    monkeypatch.setattr("app.services.launcher.locate_runtime_pid", lambda _run: None)

    def fake_kill(pid: int, sig: int) -> None:
        if sig != 0:
            killed_pids.append(pid)

    monkeypatch.setattr("app.services.launcher.os.kill", fake_kill)

    from app.services.launcher import stop_run_runtime

    stop_run_runtime(db.get_run_by_id(run["id"]))

    assert ["docker", "rm", "-f", container_name] in removed_commands
    assert killed_pids == [12345]



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



def test_supervise_container_refreshes_live_run_metadata_projection_on_heartbeat(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://projection.example")
    db.update_run_status(run["id"], "running")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-000003-projection"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-000003-projection\n",
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
    (engagement_dir / "log.md").write_text("## [14:03] Source analysis summary — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases(status, assigned_agent) VALUES (?, ?)",
            [("pending", None), ("processing", "source-analyzer")],
        )
        connection.commit()

    stale_timestamp = "2026-03-25 00:00:00"
    db.set_run_updated_at(run["id"], stale_timestamp)

    project_model = db.get_project_by_id(project["id"])
    user_model = db.get_user_by_token(token, datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    run_model = db.get_run_by_id(run["id"])
    assert project_model is not None
    assert user_model is not None
    assert run_model is not None

    monkeypatch.setattr("app.services.launcher._container_status", lambda _name: "running")
    monkeypatch.setattr("app.services.launcher._ensure_runtime_log_follower", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.launcher._running_container_stall_reason", lambda _run: None)

    def stop_after_first_heartbeat(_seconds):
        raise RuntimeError("stop-after-heartbeat")

    monkeypatch.setattr("app.services.launcher.time.sleep", stop_after_first_heartbeat)

    from app.services.launcher import _supervise_container

    try:
        _supervise_container(run_model, project_model, user_model, "container-123", None, io.BytesIO())
        raise AssertionError("expected heartbeat loop to stop test execution")
    except RuntimeError as exc:
        assert str(exc) == "stop-after-heartbeat"

    refreshed = db.get_run_by_id(run["id"])
    assert refreshed is not None
    assert refreshed.updated_at != stale_timestamp

    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata["updated_at"] == refreshed.updated_at
    assert metadata["current_phase"] == "consume-test"
    assert metadata["current_action"]["summary"] == "Processing 1 queued case(s)"



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


def test_start_container_supervisor_ignores_deleted_run_terminal_races(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://deleted-race.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None
    project_row = db.get_project_by_id(project["id"])
    assert project_row is not None
    user_row = db.get_user_by_id(project_row.user_id)
    assert user_row is not None

    class InlineThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args
            self.daemon = daemon

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr("app.services.launcher.Thread", InlineThread)

    def deleted_run_race(*args, **kwargs):
        db.delete_run(run_row.id)
        raise AssertionError("run disappeared before terminal status update")

    monkeypatch.setattr("app.services.launcher._supervise_container", deleted_run_race)

    from app.services import launcher

    with launcher._ACTIVE_CONTAINER_SUPERVISORS_LOCK:
        launcher._ACTIVE_CONTAINER_SUPERVISORS.clear()

    assert launcher._start_container_supervisor(
        run_row,
        project_row,
        user_row,
        log_handle=io.BytesIO(),
    )

    assert db.get_run_by_id(run_row.id) is None
    with launcher._ACTIVE_CONTAINER_SUPERVISORS_LOCK:
        assert run_row.id not in launcher._ACTIVE_CONTAINER_SUPERVISORS


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
                    {
                        "agent_name": "exploit-developer",
                        "status": "active",
                        "updated_at": "2026-03-31 00:00:00",
                    },
                    {
                        "agent_name": "source-analyzer",
                        "status": "active",
                        "updated_at": "2026-03-31 00:00:01",
                    },
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
                    {
                        "agent_name": "vulnerability-analyst",
                        "status": "active",
                        "updated_at": "2026-03-31 00:00:00",
                    },
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



def test_running_container_stall_reason_treats_recent_open_subagent_session_logs_as_active_runtime_agents():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://opencode-subagent-active.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale processing assignment waiting on subagent\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-opencode-subagent-active"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-opencode-subagent-active\n",
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

    (run_root / "run.json").write_text(json.dumps({"agents": []}) + "\n", encoding="utf-8")

    log_dir = run_root / "opencode-home" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    opencode_log = log_dir / "2026-03-31T000000.log"
    recent_created_at = datetime.now(tz=UTC).replace(microsecond=0)
    recent_stream_at = recent_created_at + timedelta(seconds=1)
    opencode_log.write_text(
        f"INFO {recent_created_at.strftime('%Y-%m-%dT%H:%M:%S')} service=session id=ses_testsubagent parentID=ses_parent cwd=/tmp title=Analyze API batch (@vulnerability-analyst subagent) permissionProfile=default model=openai/gpt-5.4 created\n"
        f"INFO {recent_stream_at.strftime('%Y-%m-%dT%H:%M:%S')} service=llm sessionID=ses_testsubagent agent=vulnerability-analyst mode=subagent stream\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(opencode_log, (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_ignores_stale_open_subagent_session_logs_after_runtime_timeout():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://opencode-subagent-stale.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale processing assignment waiting on subagent\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-opencode-subagent-stale"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-opencode-subagent-stale\n",
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

    (run_root / "run.json").write_text(json.dumps({"agents": []}) + "\n", encoding="utf-8")

    log_dir = run_root / "opencode-home" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    opencode_log = log_dir / "2026-03-31T000000.log"
    stale_created_at = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(seconds=1000)
    stale_stream_at = stale_created_at + timedelta(seconds=1)
    opencode_log.write_text(
        f"INFO {stale_created_at.strftime('%Y-%m-%dT%H:%M:%S')} service=session id=ses_testsubagent parentID=ses_parent cwd=/tmp title=Analyze API batch (@vulnerability-analyst subagent) permissionProfile=default model=openai/gpt-5.4 created\n"
        f"INFO {stale_stream_at.strftime('%Y-%m-%dT%H:%M:%S')} service=llm sessionID=ses_testsubagent agent=vulnerability-analyst mode=subagent stream\n",
        encoding="utf-8",
    )

    import os

    stale_runtime_epoch = datetime.now().timestamp() - 130
    os.utime(process_log, (stale_runtime_epoch, stale_runtime_epoch))
    os.utime(scope_path, (stale_runtime_epoch, stale_runtime_epoch))
    os.utime(engagement_dir / "cases.db", (stale_runtime_epoch, stale_runtime_epoch))
    os.utime(opencode_log, (stale_runtime_epoch, stale_runtime_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Processing queue assignments (vulnerability-analyst) had no matching active runtime agent after stall grace period elapsed.",
    )



def test_running_container_stall_reason_flags_unresolved_permission_prompt_in_autonomous_runtime():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://permission-stall.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text("permission prompt pending\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-permission-stall"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-permission-stall\n",
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
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute("INSERT INTO cases(status, assigned_agent) VALUES ('pending', NULL)")
        connection.commit()

    permission_asked_at = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(seconds=90)
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "agent_name": "exploit-developer",
                        "status": "active",
                        "updated_at": permission_asked_at.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    log_dir = run_root / "opencode-home" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    opencode_log = log_dir / "2026-03-31T000000.log"
    opencode_log.write_text(
        "\n".join(
            [
                f"INFO {permission_asked_at.strftime('%Y-%m-%dT%H:%M:%S')} service=permission id=per_blocked permission=external_directory patterns=[\"/usr/share/*\"] asking",
                f"INFO {permission_asked_at.strftime('%Y-%m-%dT%H:%M:%S')} service=bus type=permission.asked publishing",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "exploit",
        "queue_stalled",
        "Autonomous runtime requested interactive permission approval and never resolved it; unattended runs must stay within workspace-local inputs or fail fast instead of waiting forever.",
    )



def test_running_container_stall_reason_ignores_synthetic_queue_backed_active_agents_without_runtime_timestamp():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://synthetic-active-agent.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale queue with synthetic active agent\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-synthetic-active-agent"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-synthetic-active-agent\n",
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
            "INSERT INTO cases(status, assigned_agent) VALUES ('processing', 'source-analyzer')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "agent_name": "source-analyzer",
                        "status": "active",
                        "task_name": "source-analyzer",
                        "summary": "Processing 10 queued case(s)",
                        "updated_at": "",
                    },
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
        "Processing queue assignments (source-analyzer) had no matching active runtime agent after stall grace period elapsed.",
    )



def test_running_container_stall_reason_waits_for_recent_workflow_activity_before_flagging_processing_agent_mismatch():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://recent-workflow-activity.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale operator heartbeat\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-recent-workflow-activity"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-recent-workflow-activity\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [00:00] Source analysis summary — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(status, assigned_agent) VALUES ('processing', 'source-analyzer')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-03-31 00:00:00"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_flags_stale_processing_subset_while_other_agent_stays_active():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://mixed-processing-agents.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent runtime activity\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-09-132832-host-docker-internal"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-09-132832-host-docker-internal\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [14:03] Source analysis summary — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT, consumed_at TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent, consumed_at) VALUES (205, 'processing', 'vulnerability-analyst', '2026-04-09 13:49:39')"
        )
        for case_id in (1, 25, 64, 80):
            connection.execute(
                "INSERT INTO cases(id, status, assigned_agent, consumed_at) VALUES (?, 'processing', 'source-analyzer', '2026-04-09 14:03:59')",
                (case_id,),
            )
        connection.commit()

    recent_source_activity = datetime.fromtimestamp(datetime.now().timestamp() - 5, tz=UTC).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "source-analyzer", "status": "active", "updated_at": recent_source_activity},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    recent_epoch = datetime.now().timestamp() - 5
    old_epoch = datetime.now().timestamp() - 130
    os.utime(process_log, (recent_epoch, recent_epoch))
    os.utime(scope_path, (recent_epoch, recent_epoch))
    os.utime(log_path, (recent_epoch, recent_epoch))
    os.utime(engagement_dir / "cases.db", (recent_epoch, recent_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Processing queue assignments (vulnerability-analyst) had no matching active runtime agent after stall grace period elapsed (active agents: source-analyzer).",
    )



def test_running_container_stall_reason_allows_recent_processing_handoff_without_active_runtime_agent():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://recent-processing-handoff.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent runtime activity\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-09-140732-host-docker-internal"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-09-140732-host-docker-internal\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [14:21] Analysis summary — vulnerability-analyst\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT, consumed_at TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent, consumed_at) VALUES (10, 'processing', 'vulnerability-analyst', '2026-04-09 14:19:51')"
        )
        connection.commit()

    (run_root / "run.json").write_text(json.dumps({"agents": []}) + "\n", encoding="utf-8")

    import os

    recent_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (recent_epoch, recent_epoch))
    os.utime(scope_path, (recent_epoch, recent_epoch))
    os.utime(log_path, (recent_epoch, recent_epoch))
    os.utime(engagement_dir / "cases.db", (recent_epoch, recent_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_flags_undispatched_follow_on_fetch_even_with_recent_workflow_activity():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://undispatched-follow-on-fetch.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    fetch_timestamp_ms = int((datetime.now().timestamp() - 130) * 1000)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": fetch_timestamp_ms,
                "part": {
                    "tool": "bash",
                    "state": {
                        "output": "BATCH_FILE=/workspace/engagements/demo/scans/operator/page_batch_001.json\nBATCH_TYPE=page\nBATCH_AGENT=source-analyzer\nBATCH_COUNT=4\nBATCH_IDS=1,23,62,73\n"
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-undispatched-follow-on-fetch"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-undispatched-follow-on-fetch\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [00:00] Source analysis summary — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent) VALUES (1, 'processing', 'source-analyzer')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-03-31 00:00:00"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Fetched non-empty page batch for source-analyzer (ids: 1,23,62,73) but no matching task dispatch followed before stall grace period elapsed.",
    )



def test_running_container_stall_reason_ignores_stale_metadata_active_agent_for_orphaned_follow_on_fetch():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://stale-metadata-active-agent.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    fetch_timestamp_ms = int((datetime.now().timestamp() - 130) * 1000)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": fetch_timestamp_ms,
                "part": {
                    "tool": "bash",
                    "state": {
                        "output": "BATCH_FILE=/workspace/engagements/demo/scans/operator/page_batch_001.json\nBATCH_TYPE=page\nBATCH_AGENT=source-analyzer\nBATCH_COUNT=5\nBATCH_IDS=1,25,64,80,88\n"
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-09-132832-host-docker-internal"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-09-132832-host-docker-internal\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [13:54] Data batch recorded — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        for case_id in (1, 25, 64, 80, 88):
            connection.execute(
                "INSERT INTO cases(id, status, assigned_agent) VALUES (?, 'processing', 'source-analyzer')",
                (case_id,),
            )
        connection.commit()

    stale_updated_at = datetime.fromtimestamp(datetime.now().timestamp() - 8 * 3600, tz=UTC).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "source-analyzer", "status": "active", "updated_at": stale_updated_at},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Fetched non-empty page batch for source-analyzer (ids: 1,25,64,80,88) but no matching task dispatch followed before stall grace period elapsed.",
    )



def test_running_container_stall_reason_accepts_subagent_launch_from_opencode_logs_when_process_log_misses_task_dispatch():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://resume-opencode-log.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    fetch_epoch = datetime.now().timestamp() - 130
    fetch_timestamp_ms = int(fetch_epoch * 1000)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": fetch_timestamp_ms,
                "part": {
                    "tool": "bash",
                    "state": {
                        "output": "BATCH_FILE=/workspace/engagements/demo/scans/resume_api_batch_recovered_1775109860.json\nBATCH_TYPE=api\nBATCH_AGENT=vulnerability-analyst\nBATCH_COUNT=8\nBATCH_IDS=148,149,150,151,211,212,217,219\n"
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    opencode_log_dir = run_root / "opencode-home" / "log"
    opencode_log_dir.mkdir(parents=True, exist_ok=True)
    opencode_log = opencode_log_dir / "2026-04-02T060329.log"
    launched_at = datetime.fromtimestamp(fetch_epoch + 10, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    launched_at_ms = int((fetch_epoch + 10) * 1000)
    opencode_log.write_text(
        f"INFO  {launched_at} +0ms service=session id=ses_resume slug=tidy-garden version=1.3.7 projectID=global directory=/workspace parentID=ses_operator title=Resume API triage (@vulnerability-analyst subagent) permission=[{{\"permission\":\"todowrite\",\"pattern\":\"*\",\"action\":\"deny\"}},{{\"permission\":\"task\",\"pattern\":\"*\",\"action\":\"deny\"}}] time={{\"created\":{launched_at_ms},\"updated\":{launched_at_ms}}} created\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-resume-opencode-log"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-resume-opencode-log\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [00:00] API triage resumed — operator\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent) VALUES (148, 'processing', 'vulnerability-analyst')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-03-31 00:00:00"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(opencode_log, (fresh_epoch, fresh_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_accepts_subagent_llm_activity_from_opencode_logs_when_session_create_is_missing():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://resume-opencode-llm.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    fetch_epoch = datetime.now().timestamp() - 130
    fetch_timestamp_ms = int(fetch_epoch * 1000)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": fetch_timestamp_ms,
                "part": {
                    "tool": "bash",
                    "state": {
                        "output": "BATCH_FILE=/workspace/engagements/demo/scans/resume_api_batch_recovered_1775109860.json\nBATCH_TYPE=api\nBATCH_AGENT=vulnerability-analyst\nBATCH_COUNT=7\nBATCH_IDS=20,31,37,38,39,40,80\n"
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    opencode_log_dir = run_root / "opencode-home" / "log"
    opencode_log_dir.mkdir(parents=True, exist_ok=True)
    opencode_log = opencode_log_dir / "2026-04-02T072215.log"
    stream_at = datetime.fromtimestamp(fetch_epoch + 6, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    opencode_log.write_text(
        f"INFO  {stream_at} +0ms service=llm providerID=openai modelID=gpt-5.4 sessionID=ses_batch small=false agent=vulnerability-analyst mode=subagent stream\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-resume-opencode-llm"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-resume-opencode-llm\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [00:00] API triage resumed — operator\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent) VALUES (20, 'processing', 'vulnerability-analyst')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-03-31 00:00:00"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(opencode_log, (fresh_epoch, fresh_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_parse_runtime_activity_timestamp_treats_naive_iso_strings_as_utc(monkeypatch):
    import os
    import time

    from app.services.launcher import _parse_runtime_activity_timestamp

    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Asia/Singapore")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        naive_value = _parse_runtime_activity_timestamp("2026-04-02T08:30:37")
        utc_value = _parse_runtime_activity_timestamp("2026-04-02T08:30:37Z")
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        if hasattr(time, "tzset"):
            time.tzset()

    assert naive_value == utc_value



def test_running_container_stall_reason_prefers_latest_non_empty_fetch_in_multi_fetch_output():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://multi-fetch-output.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    fetch_timestamp_ms = int((datetime.now().timestamp() - 130) * 1000)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": fetch_timestamp_ms,
                "part": {
                    "tool": "bash",
                    "state": {
                        "output": "BATCH_FILE=/workspace/engagements/demo/tmp/resume-batch.json\nBATCH_TYPE=api\nBATCH_AGENT=vulnerability-analyst\nBATCH_COUNT=0\nBATCH_IDS=\nBATCH_NOTE=Refusing fetch for vulnerability-analyst: 10 case(s) already processing\nBATCH_FILE=/workspace/engagements/demo/tmp/resume-batch.json\nBATCH_TYPE=page\nBATCH_AGENT=source-analyzer\nBATCH_COUNT=3\nBATCH_IDS=41,42,43\nBATCH_PATHS=/,/robots.txt,/main.js\n"
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-multi-fetch-output"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-multi-fetch-output\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("## [00:00] Source analysis summary — source-analyzer\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(id, status, assigned_agent) VALUES (41, 'processing', 'source-analyzer')"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-03-31 00:00:00"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    fresh_epoch = datetime.now().timestamp() - 5
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))
    os.utime(log_path, (fresh_epoch, fresh_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Fetched non-empty page batch for source-analyzer (ids: 41,42,43) but no matching task dispatch followed before stall grace period elapsed.",
    )



def test_running_container_stall_reason_flags_pending_queue_without_active_runtime_agent_after_dispatch_grace():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://pending-dispatch-gap.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent runtime heartbeat\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-pending-dispatch-gap"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-pending-dispatch-gap\n",
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
            "INSERT INTO cases(status, assigned_agent) VALUES ('pending', NULL)"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "report-writer", "status": "completed"},
                    {"agent_name": "operator", "status": "completed"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "consume_test",
        "queue_stalled",
        "Pending queue items remained undispatched with no active runtime agent after dispatch grace period elapsed.",
    )



def test_running_container_stall_reason_keeps_pending_queue_alive_when_runtime_agent_is_active():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://pending-dispatch-active.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("recent runtime heartbeat\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-pending-dispatch-active"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-pending-dispatch-active\n",
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
            "INSERT INTO cases(status, assigned_agent) VALUES ('pending', NULL)"
        )
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 130
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None



def test_running_container_stall_reason_flags_orphaned_report_phase_without_current_task_or_active_agent():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://orphaned-report.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run["engagement_root"])
    runtime_dir = run_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    process_log = runtime_dir / "process.log"
    process_log.write_text("stale runtime output\n", encoding="utf-8")

    opencode_log = run_root / "opencode-home" / "log" / "2026-03-31T000000.log"
    opencode_log.parent.mkdir(parents=True, exist_ok=True)
    opencode_log.write_text(
        "INFO  2026-03-31T00:00:05 +0ms service=bus type=message.part.updated publishing\n",
        encoding="utf-8",
    )
    opencode_log.touch()

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-orphaned-report"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-orphaned-report\n",
        encoding="utf-8",
    )
    scope_path = engagement_dir / "scope.json"
    scope_path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "report",
                "phases_completed": ["recon", "collect", "consume_test", "exploit"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    log_path = engagement_dir / "log.md"
    log_path.write_text("stale report phase\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "current_phase": "report",
                "current_task_name": None,
                "current_agent_name": None,
                "agents": [
                    {
                        "agent_name": "operator",
                        "phase": "report",
                        "status": "completed",
                        "task_name": "todowrite",
                        "updated_at": "2026-03-31 00:00:40",
                    },
                    {
                        "agent_name": "report-writer",
                        "phase": "report",
                        "status": "idle",
                        "task_name": "",
                        "updated_at": "",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import os

    old_epoch = datetime.now().timestamp() - 950
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(log_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) == (
        "report",
        "queue_stalled",
        "Run remained in report with no active runtime agent, current task, or queued work before stall timeout elapsed.",
    )



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



def test_auto_resume_skips_report_phase_recovery(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice-report-resume")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://report-only.example")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000000-report-stall"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000000-report-stall\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "current_phase": "report",
                "phases_completed": ["recon", "collect", "consume_test", "exploit"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)")
        connection.executemany("INSERT INTO cases(status) VALUES (?)", [("done",), ("done",)])
        connection.commit()

    launched = {"count": 0}

    def fake_launch(*args, **kwargs):
        launched["count"] += 1
        raise AssertionError("report phase must not auto-resume")

    monkeypatch.setattr("app.services.launcher._launch_runtime_container", fake_launch)

    from app.services.launcher import _maybe_auto_resume_run

    project_obj = db.get_project_by_id(project["id"])
    user_obj = db.get_user_by_username("alice-report-resume")
    run_obj = db.get_run_by_id(run["id"])
    assert project_obj is not None
    assert user_obj is not None
    assert run_obj is not None

    resumed = _maybe_auto_resume_run(
        project_obj,
        run_obj,
        user_obj,
        phase="report",
        reason_code="runtime_disappeared",
        reason_text="report writer disappeared",
    )

    assert resumed is False
    assert launched["count"] == 0
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata.get("auto_resume_count") in (None, 0)
    events = db.list_events_for_run(run["id"])
    assert not any(event.event_type == "run.resumed" for event in events)



def test_auto_resume_allows_report_phase_recovery_for_continuous_targets(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice-continuous-report-resume")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://www.example.com")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-31-000001-continuous-report-stall"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-31-000001-continuous-report-stall\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://www.example.com",
                "hostname": "www.example.com",
                "status": "in_progress",
                "current_phase": "report",
                "phases_completed": ["recon", "collect", "consume_test", "exploit"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)")
        connection.executemany("INSERT INTO cases(status) VALUES (?)", [("done",), ("done",)])
        connection.commit()

    seed_root = run_root / "seed"
    seed_root.mkdir(parents=True, exist_ok=True)
    (seed_root / "env.json").write_text(
        json.dumps({"REDTEAM_CONTINUOUS_TARGETS": "https://www.example.com"}) + "\n",
        encoding="utf-8",
    )

    launched = {"container": 0, "supervisor": 0}

    def fake_launch(*args, **kwargs):
        launched["container"] += 1
        return None

    def fake_start(*args, **kwargs):
        launched["supervisor"] += 1
        log_handle = kwargs.get("log_handle")
        if log_handle is not None:
            log_handle.close()
        return True

    monkeypatch.setattr("app.services.launcher._launch_runtime_container", fake_launch)
    monkeypatch.setattr("app.services.launcher._start_container_supervisor", fake_start)

    from app.services.launcher import _maybe_auto_resume_run

    project_obj = db.get_project_by_id(project["id"])
    user_obj = db.get_user_by_username("alice-continuous-report-resume")
    run_obj = db.get_run_by_id(run["id"])
    assert project_obj is not None
    assert user_obj is not None
    assert run_obj is not None

    resumed = _maybe_auto_resume_run(
        project_obj,
        run_obj,
        user_obj,
        phase="report",
        reason_code="runtime_disappeared",
        reason_text="continuous observation hold detached",
    )

    assert resumed is True
    assert launched["container"] == 1
    assert launched["supervisor"] == 1
    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "running"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
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
    (engagement_dir / "report.md").write_text(
        "# Penetration Test Report\n\n"
        "**Date**: 2026-03-28 — Completed\n"
        "**Target**: https://example.com  **Scope**: example.com, *.example.com  **Status**: Completed\n\n"
        "## Executive Summary\n"
        "- Target: https://example.com\n"
        "- Confirmed findings: 0 total\n\n"
        "## Scope and Methodology\n"
        "- Completed phases: recon, collect, consume_test, exploit, report\n\n"
        "## Findings\n"
        "No confirmed findings were recorded in findings.md.\n\n"
        "## Attack Narrative\n"
        "The engagement followed the recorded orchestrator workflow and completed reporting successfully.\n\n"
        "## Recommendations\n"
        "- Continue monitoring.\n\n"
        "## Appendix\n"
        "- cases.db rows: 2\n"
        "- surfaces.jsonl rows: 0\n",
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
    from app.services.launcher import engagement_completion_state

    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None
    assert engagement_completion_state(latest) == (True, "Engagement completed and finalized.")

    normalized = json.loads((engagement_dir / "scope.json").read_text(encoding="utf-8"))
    assert normalized["status"] == "complete"


def test_engagement_completion_state_repairs_completed_report_scope_from_log():
    client = TestClient(app)
    token = register_and_login(client, "alice-repair-report-scope")
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
                "current_phase": "report",
                "phases_completed": ["recon", "collect", "consume_test", "exploit"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "log.md").write_text(
        "# Engagement Log\n\n"
        "## [04:15] Report complete — operator\n\n"
        "**Action**: phase 5 report\n"
        "**Result**: persisted final report to report.md and closing engagement after final queue/coverage verification\n\n"
        "## [04:15] Run stop — operator\n\n"
        "**Action**: stop_reason=completed\n"
        "**Result**: engagement complete; queue empty, collection healthy, surface coverage passed, exploit/report phases finished\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text(
        "# Penetration Test Report\n\n"
        "**Date**: 2026-03-30 — Completed\n"
        "**Target**: https://example.com  **Scope**: example.com, *.example.com  **Status**: Completed\n\n"
        "## Executive Summary\n"
        "- Target: https://example.com\n"
        "- Confirmed findings: 0 total\n\n"
        "## Scope and Methodology\n"
        "- Completed phases: recon, collect, consume_test, exploit\n\n"
        "## Findings\n"
        "No confirmed findings were recorded in findings.md.\n\n"
        "## Attack Narrative\n"
        "The engagement followed the recorded orchestrator workflow and completed reporting successfully.\n\n"
        "## Recommendations\n"
        "- Continue monitoring.\n\n"
        "## Appendix\n"
        "- cases.db rows: 2\n"
        "- surfaces.jsonl rows: 0\n",
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
    from app.services.launcher import engagement_completion_state

    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None
    assert engagement_completion_state(latest) == (True, "Engagement completed and finalized.")

    normalized = json.loads((engagement_dir / "scope.json").read_text(encoding="utf-8"))
    assert normalized["current_phase"] == "complete"
    assert normalized["phases_completed"] == ["recon", "collect", "consume_test", "exploit", "report"]


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
        "**Target**: https://example.com  **Scope**: example.com, *.example.com  **Status**: In Progress\n"
        "**Status**: In Progress (testing queue completed; report phase active)\n\n"
        "## Appendix\n\n"
        "### C. Full scope.json\n\n"
        "```json\n"
        "{\n"
        "  \"status\": \"in_progress\",\n"
        "  \"current_phase\": \"report\"\n"
        "}\n"
        "```\n",
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

    normalized_scope = json.loads((engagement_dir / "scope.json").read_text(encoding="utf-8"))
    log_text = (engagement_dir / "log.md").read_text(encoding="utf-8")
    report_text = (engagement_dir / "report.md").read_text(encoding="utf-8")

    assert normalized_scope["end_time"].endswith("Z")
    assert "- **Status**: Completed" in log_text
    assert "**Date**: 2026-03-30 — Completed" in report_text
    assert "**Status**: Completed" in report_text
    assert '"status": "complete"' in report_text
    assert '"current_phase": "complete"' in report_text
    assert "In Progress" not in report_text


def test_normalize_active_scope_bootstraps_substantive_report_from_findings():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")

    run_root = Path(run["engagement_root"])
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-09-000000-local"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-09-000000-local\n",
        encoding="utf-8",
    )
    (engagement_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://127.0.0.1:8000",
                "scope": ["http://127.0.0.1:8000"],
                "status": "complete",
                "current_phase": "complete",
                "start_time": "2026-04-09T05:20:40Z",
                "end_time": "2026-04-09T06:12:41Z",
                "phases_completed": ["recon", "collect", "consume_test", "exploit", "report"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (engagement_dir / "findings.md").write_text(
        "# Findings\n\n"
        "## [FINDING-SA-001] Hardcoded test credentials exposed in public JavaScript bundle\n"
        "- **Discovered by**: source-analyzer\n"
        "- **Severity**: HIGH\n"
        "- **OWASP Category**: A07:2021 Identification and Authentication Failures\n"
        "- **Type**: Hardcoded Credential Disclosure\n"
        "- **Parameter**: `email,password` in `POST /rest/user/login`\n"
        "- **Evidence**: `downloads/source-analysis/main.js` contains `testingPassword=\"IamUsedForTesting\"`.\n"
        "- **Impact**: Any unauthenticated user can authenticate with the exposed testing account.\n",
        encoding="utf-8",
    )
    (engagement_dir / "report.md").write_text("**Date**: 2026-04-09 — Completed\n", encoding="utf-8")
    (engagement_dir / "log.md").write_text("# Engagement Log\n", encoding="utf-8")
    (engagement_dir / "surfaces.jsonl").write_text("", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('done')")
        connection.commit()

    from app import db as app_db
    from app.services.launcher import engagement_completion_state, normalize_active_scope

    latest = app_db.get_run_by_id(run["id"])
    assert latest is not None

    normalize_active_scope(latest)

    report_text = (engagement_dir / "report.md").read_text(encoding="utf-8")
    assert "## Executive Summary" in report_text
    assert "## Findings" in report_text
    assert "### [FINDING-001] Hardcoded test credentials exposed in public JavaScript bundle" in report_text
    assert "- **Original ID**: FINDING-SA-001" in report_text
    assert "### C. Full scope.json" in report_text
    assert engagement_completion_state(latest) == (True, "Engagement completed and finalized.")


def test_auto_launch_marks_completed_when_scope_finalizes_before_runtime_exits(monkeypatch):
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
            engagement_dir = workspace / "engagements" / "2026-03-28-000000-example-live-complete"
            engagement_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "engagements" / ".active").write_text(
                "engagements/2026-03-28-000000-example-live-complete\n",
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

    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="container-123\n", stderr="")
        if command[:4] == ["docker", "inspect", "-f", "{{.State.Status}}"]:
            return subprocess.CompletedProcess(command, 0, stdout="running\n", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("app.services.launcher.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeLogFollower())
    monkeypatch.setattr("app.services.launcher.Thread", ImmediateThread)
    monkeypatch.setattr(
        "app.services.launcher.engagement_completion_state",
        lambda _run: (True, "Engagement completed and finalized."),
    )
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
    assert any(command[:3] == ["docker", "rm", "-f"] for command in captured)


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
            (engagement_dir / "report.md").write_text(
                "# Report\n\n## Executive Summary\n- completed\n\n## Findings\n- none\n",
                encoding="utf-8",
            )
            (engagement_dir / "surfaces.jsonl").write_text(
                json.dumps({"surface_type": "api_documentation", "target": "GET /api-docs/", "status": "covered"})
                + "\n",
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


def test_start_run_runtime_passes_continuous_observation_env(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "ContinuousObservation",
            "env_json": '{"REDTEAM_CONTINUOUS_TARGETS":"https://www.example.com","OBSERVATION_SECONDS":"300"}',
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
        run = create_run(client, token, project["id"], "https://www.example.com")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    assert run["status"] == "running"
    joined = " ".join(captured["command"])
    assert "REDTEAM_CONTINUOUS_TARGETS=https://www.example.com" in joined
    assert "OBSERVATION_SECONDS=300" in joined


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
    auth_seed = json.loads((run_root / "seed" / "auth.json").read_text(encoding="utf-8"))
    assert auth_seed["headers"]["Authorization"] == "Bearer abc"
    assert auth_seed["cookies"] == {}
    assert auth_seed["tokens"] == {}
    assert auth_seed["discovered_credentials"] == []
    assert auth_seed["validated_credentials"] == []
    assert auth_seed["credentials"] == []
    assert json.loads((run_root / "seed" / "env.json").read_text(encoding="utf-8"))["HTTP_PROXY"] == "http://proxy:8080"


def test_prepare_run_runtime_normalizes_legacy_auth_seed_credentials():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "LegacyAuthSeed",
            "auth_json": '{"credentials":[{"type":"password","username":"demo","password":"secret"}],"headers":{"Authorization":"Bearer abc"}}',
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()

    run = create_run(client, token, project["id"], "https://legacy-seed.example")
    auth_seed = json.loads(Path(run["engagement_root"], "seed", "auth.json").read_text(encoding="utf-8"))
    assert auth_seed["headers"]["Authorization"] == "Bearer abc"
    assert auth_seed["discovered_credentials"] == [
        {"type": "password", "username": "demo", "password": "secret"}
    ]
    assert auth_seed["validated_credentials"] == []
    assert auth_seed["credentials"] == [
        {"type": "password", "username": "demo", "password": "secret"}
    ]


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



def test_auto_resume_resets_budget_after_queue_progress(monkeypatch):
    from app.services import launcher

    client = TestClient(app)
    token = register_and_login(client, "alice-resume-progress")
    project = create_project(client, token)

    object.__setattr__(settings, "auto_launch_runs", False)
    try:
        run = create_run(client, token, project["id"], "https://progress-resume.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    project_model = db.get_project_by_id(project["id"])
    assert project_model is not None
    user_model = db.get_user_by_id(project_model.user_id)
    assert user_model is not None

    workspace = Path(latest.engagement_root) / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-010000-example-progress-resume"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-010000-example-progress-resume\n",
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

    cases_db = engagement_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("pending",), ("pending",)],
        )
        connection.commit()

    monkeypatch.setattr("app.services.launcher._launch_runtime_container", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.launcher._start_container_supervisor", lambda *args, **kwargs: True)

    assert launcher._maybe_auto_resume_run(
        project_model,
        latest,
        user_model,
        phase="consume-test",
        reason_code="engagement_incomplete",
        reason_text="queue still has pending work",
    )

    metadata = json.loads((Path(latest.engagement_root) / "run.json").read_text(encoding="utf-8"))
    assert metadata["auto_resume_count"] == 1
    assert metadata["auto_resume_progress"] == 1

    with sqlite3.connect(cases_db) as connection:
        connection.execute("DELETE FROM cases")
        connection.executemany(
            "INSERT INTO cases(status) VALUES (?)",
            [("done",), ("done",), ("pending",)],
        )
        connection.commit()

    refreshed = db.get_run_by_id(run["id"])
    assert refreshed is not None
    assert launcher._maybe_auto_resume_run(
        project_model,
        refreshed,
        user_model,
        phase="consume-test",
        reason_code="engagement_incomplete",
        reason_text="queue still has pending work",
    )

    metadata = json.loads((Path(latest.engagement_root) / "run.json").read_text(encoding="utf-8"))
    assert metadata["auto_resume_count"] == 1
    assert metadata["auto_resume_progress"] == 2



def test_auto_resume_replaces_existing_supervisor_handoff(monkeypatch):
    from app.services import launcher

    client = TestClient(app)
    token = register_and_login(client, "alice-resume-handoff")
    project = create_project(client, token)

    object.__setattr__(settings, "auto_launch_runs", False)
    try:
        run = create_run(client, token, project["id"], "https://resume-handoff.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    project_model = db.get_project_by_id(project["id"])
    assert project_model is not None
    user_model = db.get_user_by_id(project_model.user_id)
    assert user_model is not None

    workspace = Path(latest.engagement_root) / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-015000-example-resume-handoff"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-015000-example-resume-handoff\n",
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

    launched = []
    started_threads: list[object] = []

    class DummyThread:
        def __init__(self, *, target, args=(), daemon=None):
            self.target = target
            self.args = args
            started_threads.append(self)

        def start(self):
            return None

    monkeypatch.setattr(
        "app.services.launcher._launch_runtime_container",
        lambda *args, **kwargs: launched.append("launched") or None,
    )
    monkeypatch.setattr("app.services.launcher.Thread", DummyThread)

    with launcher._ACTIVE_CONTAINER_SUPERVISORS_LOCK:
        launcher._ACTIVE_CONTAINER_SUPERVISORS.clear()

    try:
        assert launcher._start_container_supervisor(
            latest,
            project_model,
            user_model,
            log_follower=None,
            log_handle=io.BytesIO(),
        )
        first_token = launcher._ACTIVE_CONTAINER_SUPERVISORS[latest.id]

        assert launcher._maybe_auto_resume_run(
            project_model,
            latest,
            user_model,
            phase="exploit",
            reason_code="runtime_disappeared",
            reason_text="Runtime supervisor disappeared before the engagement reached a terminal state.",
        )

        second_token = launcher._ACTIVE_CONTAINER_SUPERVISORS[latest.id]
        assert second_token is not first_token
        assert launched == ["launched"]
        assert len(started_threads) == 2
    finally:
        with launcher._ACTIVE_CONTAINER_SUPERVISORS_LOCK:
            launcher._ACTIVE_CONTAINER_SUPERVISORS.clear()



def test_auto_resume_requeues_orphaned_processing_cases_before_resume(monkeypatch):
    from app.services import launcher

    client = TestClient(app)
    token = register_and_login(client, "alice-resume-orphaned")
    project = create_project(client, token)

    object.__setattr__(settings, "auto_launch_runs", False)
    try:
        run = create_run(client, token, project["id"], "https://orphaned-processing-resume.example")
    finally:
        object.__setattr__(settings, "auto_launch_runs", False)

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    project_model = db.get_project_by_id(project["id"])
    assert project_model is not None
    user_model = db.get_user_by_id(project_model.user_id)
    assert user_model is not None

    workspace = Path(latest.engagement_root) / "workspace"
    engagement_dir = workspace / "engagements" / "2026-03-30-020000-example-orphaned-processing"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-03-30-020000-example-orphaned-processing\n",
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
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT, consumed_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases(status, assigned_agent, consumed_at) VALUES (?, ?, ?)",
            [
                ("processing", "source-analyzer", "2026-04-02 09:21:39"),
                ("done", None, None),
            ],
        )
        connection.commit()

    (Path(latest.engagement_root) / "run.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent_name": "operator", "status": "active", "updated_at": "2026-04-02 09:21:39"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    launched = []
    monkeypatch.setattr(
        "app.services.launcher._launch_runtime_container",
        lambda *args, **kwargs: launched.append("launched") or None,
    )
    monkeypatch.setattr("app.services.launcher._start_container_supervisor", lambda *args, **kwargs: True)

    assert launcher._maybe_auto_resume_run(
        project_model,
        latest,
        user_model,
        phase="consume-test",
        reason_code="queue_stalled",
        reason_text="Processing queue assignments (source-analyzer) had no matching active runtime agent after stall grace period elapsed.",
    )

    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        row = connection.execute(
            "SELECT status, assigned_agent, consumed_at FROM cases WHERE id = 1"
        ).fetchone()
    assert row == ("pending", None, None)
    assert launched == ["launched"]

    metadata = json.loads((Path(latest.engagement_root) / "run.json").read_text(encoding="utf-8"))
    assert metadata["auto_resume_count"] == 1
    events = db.list_events_for_run(run["id"])
    assert any(
        event.event_type == "run.resumed"
        and "Re-queued 1 orphaned processing case(s) from source-analyzer before /resume." in event.summary
        for event in events
    )


def test_running_container_stall_reason_grants_dispatch_grace_after_auto_resume():
    client = TestClient(app)
    token = register_and_login(client, "alice-auto-resume-grace")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://resume-grace.example")
    db.update_run_status(run["id"], "running")

    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    run_root = Path(run_row.engagement_root)
    process_log = run_root / "runtime" / "process.log"
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text("resume dispatched\n", encoding="utf-8")

    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-02-093000-auto-resume-grace"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-02-093000-auto-resume-grace\n",
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
    log_path = engagement_dir / "log.md"
    log_path.write_text("waiting for resumed dispatch\n", encoding="utf-8")
    with sqlite3.connect(engagement_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(status) VALUES ('pending')")
        connection.commit()

    import os

    old_epoch = datetime.now().timestamp() - 240
    os.utime(process_log, (old_epoch, old_epoch))
    os.utime(scope_path, (old_epoch, old_epoch))
    os.utime(log_path, (old_epoch, old_epoch))
    os.utime(engagement_dir / "cases.db", (old_epoch, old_epoch))

    (run_root / "run.json").write_text(
        json.dumps(
            {
                "current_phase": "consume_test",
                "current_task_name": None,
                "current_agent_name": None,
                "auto_resume_started_at": datetime.now().timestamp(),
                "agents": [
                    {
                        "agent_name": "operator",
                        "phase": "consume_test",
                        "status": "active",
                        "updated_at": "2026-04-02 09:33:10",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from app.services.launcher import _running_container_stall_reason

    assert _running_container_stall_reason(run_row) is None
