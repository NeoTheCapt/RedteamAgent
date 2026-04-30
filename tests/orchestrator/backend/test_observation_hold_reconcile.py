import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.db import database_path
from app.main import app


def register_and_login(client: TestClient, username: str) -> str:
    password = "correct horse battery staple"
    register_response = client.post("/auth/register", json={"username": username, "password": password})
    assert register_response.status_code in {200, 201}
    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def create_project(client: TestClient, token: str, name: str = "Observation Hold") -> dict:
    response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


def test_reconcile_marks_detached_continuous_observation_hold_completed(monkeypatch, isolate_data_dir):
    client = TestClient(app)
    token = register_and_login(client, "alice-observation-hold")
    project = create_project(client, token)

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://www.okx.com"},
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
    running = db.get_run_by_id(run["id"])
    assert running is not None

    run_root = Path(run["engagement_root"])
    (run_root / "seed").mkdir(parents=True, exist_ok=True)
    (run_root / "seed" / "env.json").write_text(
        json.dumps({"REDTEAM_CONTINUOUS_TARGETS": "www.okx.com"}) + "\n",
        encoding="utf-8",
    )
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-29-000000-www-okx-com"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-29-000000-www-okx-com\n",
        encoding="utf-8",
    )
    report = "\n".join(
        [
            "## Executive Summary",
            "Continuous observation report.",
            "## Scope and Methodology",
            "Scope and methodology details.",
            "## Findings",
            "No confirmed findings.",
            "## Attack Narrative",
            "Narrative details.",
            "## Recommendations",
            "Recommendation details.",
            "## Appendix",
            "Appendix details.",
        ]
    )
    (engagement_dir / "report.md").write_text(report + ("\nsubstantive detail" * 60), encoding="utf-8")
    (engagement_dir / "log.md").write_text(
        "## [08:24] Observation hold active — operator\n"
        "**Result**: runtime attached for https://www.okx.com; heartbeat every 300s\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    from app.services.runs import _reconcile_run_status

    reconciled = _reconcile_run_status(running)
    assert reconciled.status == "completed"
    assert stopped == []

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata.get("stop_reason_code") is None
    assert metadata.get("stop_reason_text") is None


def test_reconcile_repairs_failed_continuous_observation_hold(monkeypatch, isolate_data_dir):
    client = TestClient(app)
    token = register_and_login(client, "alice-observation-hold-completed")
    project = create_project(client, token, name="Observation Hold Completed")

    create_run = client.post(
        f"/projects/{project['id']}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "https://www.okx.com"},
    )
    assert create_run.status_code == 201
    run = create_run.json()
    db.update_run_status(run["id"], "failed")
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()
    completed = db.get_run_by_id(run["id"])
    assert completed is not None

    run_root = Path(run["engagement_root"])
    (run_root / "seed").mkdir(parents=True, exist_ok=True)
    (run_root / "seed" / "env.json").write_text(
        json.dumps({"REDTEAM_CONTINUOUS_TARGETS": "www.okx.com"}) + "\n",
        encoding="utf-8",
    )
    workspace = run_root / "workspace"
    engagement_dir = workspace / "engagements" / "2026-04-29-010000-www-okx-com"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "engagements" / ".active").write_text(
        "engagements/2026-04-29-010000-www-okx-com\n",
        encoding="utf-8",
    )
    report = "\n".join(
        [
            "## Executive Summary",
            "Continuous observation report.",
            "## Scope and Methodology",
            "Scope and methodology details.",
            "## Findings",
            "No confirmed findings.",
            "## Attack Narrative",
            "Narrative details.",
            "## Recommendations",
            "Recommendation details.",
            "## Appendix",
            "Appendix details.",
        ]
    )
    (engagement_dir / "report.md").write_text(report + ("\nsubstantive detail" * 60), encoding="utf-8")
    (engagement_dir / "log.md").write_text(
        "## [08:24] Observation hold active — operator\n"
        "**Result**: runtime attached for https://www.okx.com; heartbeat every 300s\n",
        encoding="utf-8",
    )
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stop_reason_code": "incomplete_terminal_state",
                "stop_reason_text": "Continuous observation hold active.",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: None)
    stopped: list[int] = []
    monkeypatch.setattr("app.services.runs.stop_run_runtime", lambda reconciled_run: stopped.append(reconciled_run.id))

    from app.services.runs import _reconcile_run_status

    reconciled = _reconcile_run_status(completed)
    assert reconciled.status == "completed"
    assert stopped == []

    latest = db.get_run_by_id(run["id"])
    assert latest is not None
    assert latest.status == "completed"
    metadata = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    assert metadata.get("stop_reason_code") is None
    assert metadata.get("stop_reason_text") is None
