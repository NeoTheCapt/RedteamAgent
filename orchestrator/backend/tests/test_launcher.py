import json
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
    assert metadata["run_id"] == run["id"]
    assert metadata["target"] == "https://example.com"
    assert metadata["engagement_root"] == run["engagement_root"]


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
