import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

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

    class FakeProcess:
        def wait(self):
            return 0

    monkeypatch.setattr("app.services.launcher.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeProcess())
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

    class FakeProcess:
        def __init__(self):
            self.wait_calls = 0

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd="opencode", timeout=timeout)
            return 0

    class ImmediateThread:
        def __init__(self, *, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr("app.services.launcher.subprocess.Popen", lambda *args, **kwargs: FakeProcess())
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
    assert latest.status == "completed"
