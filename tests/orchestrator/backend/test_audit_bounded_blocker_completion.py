import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import db
from app.main import app


def register_and_login(client: TestClient, username: str) -> str:
    client.post("/auth/register", json={"username": username, "password": "password123"})
    response = client.post("/auth/login", json={"username": username, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_project(client: TestClient, token: str) -> dict:
    response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Bounded Blocker Audit"},
    )
    assert response.status_code == 201
    return response.json()


def create_run(client: TestClient, token: str, project_id: int) -> dict:
    response = client.post(
        f"/projects/{project_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://bounded-blocker.example"},
    )
    assert response.status_code == 201
    return response.json()


def test_supervisor_marks_explicit_bounded_blocker_completed(monkeypatch):
    from app.services import launcher

    client = TestClient(app)
    token = register_and_login(client, "alice-bounded-blocker-audit")
    project = create_project(client, token)
    run = create_run(client, token, project["id"])
    db.update_run_status(run["id"], "running")
    run_row = db.get_run_by_id(run["id"])
    assert run_row is not None

    reason = (
        "cases 195/196 still require an authenticated session and live switch-account request bodies; "
        "new bounded auth acquisition pass confirmed Singapore switch-site/verification gating on registration "
        "and no credentials for login, so no further non-duplicative bounded queue action remains"
    )

    class FinishedProcess:
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(launcher, "normalize_active_scope", lambda run: None)
    monkeypatch.setattr(launcher, "engagement_completion_state", lambda run: (False, reason))
    monkeypatch.setattr(launcher, "_init_only_exit", lambda run: False)

    launcher._supervise_process(
        run_row,
        FinishedProcess(),
        SimpleNamespace(close=lambda: None),
        heartbeat_interval=0,
    )

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert metadata["stop_reason_code"] == "completed_with_blockers"
    assert metadata["stop_reason_text"] == reason
