import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import run_summary


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


def setup_active_engagement(run: dict) -> Path:
    workspace = Path(run["engagement_root"], "workspace")
    engagements = workspace / "engagements"
    active_name = "2026-03-25-000000-example"
    active_dir = engagements / active_name
    active_dir.mkdir(parents=True, exist_ok=True)
    (engagements / ".active").write_text(f"engagements/{active_name}", encoding="utf-8")
    return active_dir


def test_run_summary_resolves_absolute_active_marker_before_fallback_candidates():
    client = TestClient(app)
    token = register_and_login(client, "alice-absolute-active")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")

    workspace = Path(run["engagement_root"], "workspace")
    engagements = workspace / "engagements"
    real_name = "2026-03-30-113636-host-docker-internal"
    real_dir = engagements / real_name
    real_dir.mkdir(parents=True, exist_ok=True)
    sqltest_dir = engagements / "sqltest"
    sqltest_dir.mkdir(parents=True, exist_ok=True)

    (engagements / ".active").write_text(str(real_dir.resolve()), encoding="utf-8")
    (real_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://127.0.0.1:8000",
                "hostname": "127.0.0.1",
                "port": 8000,
                "scope": ["127.0.0.1"],
                "status": "in_progress",
                "start_time": "2026-03-30T11:36:36Z",
                "phases_completed": ["recon"],
                "current_phase": "collect",
            }
        ),
        encoding="utf-8",
    )
    (real_dir / "log.md").write_text("recent activity\n", encoding="utf-8")
    with sqlite3.connect(real_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "GET",
                "http://127.0.0.1:8000/rest/admin/application-version",
                "api",
                "pending",
                "",
                "katana-xhr",
            ),
        )
        connection.commit()
    with sqlite3.connect(sqltest_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE placeholder (value TEXT)")
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["target"]["engagement_dir"] == str(real_dir.resolve())
    assert payload["coverage"]["total_cases"] == 1
    assert payload["current"]["phase"] == "collect"


def test_run_summary_recovers_from_scope_less_active_marker():
    client = TestClient(app)
    token = register_and_login(client, "alice-poisoned-active")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")

    workspace = Path(run["engagement_root"], "workspace")
    engagements = workspace / "engagements"
    real_dir = engagements / "2026-03-30-113636-host-docker-internal"
    real_dir.mkdir(parents=True, exist_ok=True)
    (real_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://127.0.0.1:8000",
                "hostname": "127.0.0.1",
                "port": 8000,
                "scope": ["127.0.0.1"],
                "status": "in_progress",
                "start_time": "2026-03-30T11:36:36Z",
                "phases_completed": ["recon"],
                "current_phase": "collect",
            }
        ),
        encoding="utf-8",
    )
    (real_dir / "log.md").write_text("recent activity\n", encoding="utf-8")
    with sqlite3.connect(real_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL)")
        connection.execute("INSERT INTO cases (type, status) VALUES (?, ?)", ("api", "pending"))
        connection.commit()

    sqltest_dir = engagements / "sqltest"
    sqltest_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqltest_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE placeholder (value TEXT)")
        connection.commit()
    (engagements / ".active").write_text("engagements/sqltest", encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["target"]["engagement_dir"] == str(real_dir)
    assert payload["coverage"]["total_cases"] == 1
    assert payload["current"]["phase"] == "collect"


def test_run_summary_combines_target_coverage_and_agent_state():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "port": 443,
                "scope": ["target.example", "*.target.example"],
                "status": "in_progress",
                "start_time": "2026-03-25T08:00:00Z",
                "phases_completed": ["recon"],
                "current_phase": "collect",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "findings.md").write_text(
        "# Findings\n\n## [FINDING-VA-001] Admin panel exposed\n\n## [FINDING-EX-002] JWT bypass\n",
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"surface_type": "account_recovery", "status": "deferred"}),
                json.dumps({"surface_type": "dynamic_render", "status": "covered"}),
                json.dumps({"surface_type": "object_reference", "status": "discovered"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO cases (type, status) VALUES (?, ?)",
            [
                ("api", "done"),
                ("api", "done"),
                ("page", "pending"),
                ("javascript", "processing"),
                ("data", "error"),
            ],
        )
        connection.commit()

    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "collect",
            "task_name": "source-analyzer",
            "agent_name": "source-analyzer",
            "summary": "Source analysis start",
        },
    )
    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.completed",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon complete",
        },
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["target"]["hostname"] == "target.example"
    assert payload["overview"]["findings_count"] == 2
    assert payload["overview"]["current_phase"] == "collect"
    assert payload["coverage"]["total_cases"] == 5
    assert payload["coverage"]["completed_cases"] == 2
    assert payload["coverage"]["remaining_surfaces"] == 2
    assert payload["coverage"]["high_risk_remaining"] == 2
    assert payload["current"]["agent_name"] == "source-analyzer"
    assert payload["current"]["summary"] == "Source analysis start"
    assert any(item["type"] == "api" and item["total"] == 2 for item in payload["coverage"]["case_types"])
    assert any(item["type"] == "account_recovery" and item["count"] == 1 for item in payload["coverage"]["surface_types"])
    assert any(
        item["agent_name"] == "source-analyzer" and item["status"] == "active" and item["phase"] == "collect"
        for item in payload["agents"]
    )
    assert any(
        item["agent_name"] == "exploit-developer" and item["status"] == "idle" and item["summary"] == "No activity yet."
        for item in payload["agents"]
    )
    assert any(
        item["agent_name"] == "operator" and item["status"] == "idle"
        for item in payload["agents"]
    )
    assert len(payload["agents"]) == 7
    assert any(item["phase"] == "collect" and item["state"] == "active" for item in payload["phases"])


def test_run_summary_uses_readonly_cases_fallback_when_live_sqlite_is_locked(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "status": "in_progress",
                "phases_completed": ["recon"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, method TEXT, url TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (type, status, assigned_agent, method, url, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("api", "done", None, "GET", "https://target.example/api/version", "katana"),
                ("api", "pending", None, "GET", "https://target.example/api/users", "katana-xhr"),
                ("javascript", "processing", "source-analyzer", "GET", "https://target.example/main.js", "katana"),
            ],
        )
        connection.commit()

    real_connect = sqlite3.connect

    def flaky_connect(database, *args, **kwargs):
        target = str(cases_db)
        if str(database) == target and not kwargs.get("uri", False):
            raise sqlite3.OperationalError("database is locked")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(run_summary.sqlite3, "connect", flaky_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["coverage"]["total_cases"] == 3
    assert payload["coverage"]["completed_cases"] == 1
    assert payload["coverage"]["pending_cases"] == 1
    assert payload["coverage"]["processing_cases"] == 1
    assert any(item["type"] == "api" and item["total"] == 2 for item in payload["coverage"]["case_types"])
    assert payload["overview"]["current_phase"] == "consume-test"


def test_run_summary_retries_suspiciously_empty_live_reads_with_snapshot(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "status": "in_progress",
                "phases_completed": ["recon"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, method TEXT, url TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (type, status, assigned_agent, method, url, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("api", "pending", None, "GET", f"https://target.example/api/{index}", "katana")
                for index in range(240)
            ],
        )
        connection.commit()

    assert cases_db.stat().st_size >= 16384

    empty_db = active_dir / "empty-live-view.db"
    with sqlite3.connect(empty_db) as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, method TEXT, url TEXT, source TEXT)"
        )
        connection.commit()

    real_connect = sqlite3.connect

    def empty_live_connect(database, *args, **kwargs):
        if str(database) == str(cases_db) and not kwargs.get("uri", False):
            return real_connect(empty_db, *args, **kwargs)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(run_summary.sqlite3, "connect", empty_live_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["coverage"]["total_cases"] == 240
    assert payload["coverage"]["pending_cases"] == 240
    assert any(item["type"] == "api" and item["total"] == 240 for item in payload["coverage"]["case_types"])


def test_run_summary_falls_back_to_latest_engagement_without_active_file():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")

    workspace = Path(run["engagement_root"], "workspace")
    active_dir = workspace / "engagements" / "2026-03-25-000000-example"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "status": "in_progress",
                "phases_completed": [],
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"]["current_phase"] == "recon"
    assert any(item["phase"] == "recon" and item["state"] == "active" for item in payload["phases"])


def test_run_summary_reports_runtime_model_verification_status():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project_response = client.post(
        "/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Model Check", "provider_id": "openai", "model_id": "gpt-5.4"},
    )
    assert project_response.status_code == 201
    project = project_response.json()
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "recon"}),
        encoding="utf-8",
    )

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "metadata": {
                            "model": {
                                "providerID": "openai",
                                "modelID": "gpt-5.4",
                            }
                        }
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_model"]["configured_provider"] == "openai"
    assert payload["runtime_model"]["configured_model"] == "gpt-5.4"
    assert payload["runtime_model"]["observed_provider"] == "openai"
    assert payload["runtime_model"]["observed_model"] == "gpt-5.4"
    assert payload["runtime_model"]["status"] == "matched"


def test_run_summary_current_activity_prefers_scope_phase_for_unknown_task_events():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )

    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "unknown",
            "task_name": "source-analyzer",
            "agent_name": "source-analyzer",
            "summary": "Analyze remaining pages",
        },
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current"]["agent_name"] == "source-analyzer"
    assert payload["current"]["phase"] == "consume-test"


def test_run_summary_keeps_late_source_analyzer_log_projection_in_consume_test():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": ["recon", "collect"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )

    for event in [
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
    ]:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["current_phase"] == "consume-test"
    assert payload["current"]["phase"] == "consume-test"
    assert any(
        item["agent_name"] == "source-analyzer" and item["status"] == "active" and item["phase"] == "consume-test"
        for item in payload["agents"]
    )
    assert any(item["phase"] == "consume-test" and item["state"] == "active" for item in payload["phases"])
    assert all(not (item["phase"] == "recon" and item["state"] == "active") for item in payload["phases"])


def test_run_summary_keeps_active_recon_labeled_subagent_work_inside_advanced_scope_phase():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": ["recon", "collect"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", "http://127.0.0.1:8000/profile", "page", "processing", "vulnerability-analyst", "katana"),
                ("GET", "http://127.0.0.1:8000/settings", "page", "processing", "vulnerability-analyst", "katana-xhr"),
            ],
        )
        connection.commit()

    for event in [
        {
            "event_type": "task.started",
            "phase": "consume-test",
            "task_name": "bash",
            "agent_name": "operator",
            "summary": "Dispatch page batch",
        },
        {
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "source-analyzer",
            "agent_name": "source-analyzer",
            "summary": "Source analysis start",
        },
    ]:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["current_phase"] == "consume-test"
    assert payload["current"]["phase"] == "consume-test"
    assert payload["current"]["agent_name"] == "source-analyzer"
    assert any(
        item["agent_name"] == "source-analyzer" and item["status"] == "active" and item["phase"] == "consume-test"
        for item in payload["agents"]
    )
    assert any(item["phase"] == "consume-test" and item["state"] == "active" for item in payload["phases"])
    assert all(not (item["phase"] == "recon" and item["state"] == "active") for item in payload["phases"])



def test_run_summary_prefers_processing_agents_over_stale_runtime_phase_and_completed_operator_task():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": ["recon", "collect"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", "http://127.0.0.1:8000/api/users", "api", "processing", "vulnerability-analyst", "katana"),
                ("GET", "http://127.0.0.1:8000/api/orders", "api", "processing", "vulnerability-analyst", "katana-xhr"),
                ("GET", "http://127.0.0.1:8000/app.js", "javascript", "processing", "source-analyzer", "katana"),
            ],
        )
        connection.commit()

    for event in [
        {
            "event_type": "phase.completed",
            "phase": "recon",
            "task_name": "recon",
            "agent_name": "operator",
            "summary": "recon completed",
        },
        {
            "event_type": "task.completed",
            "phase": "consume-test",
            "task_name": "bash",
            "agent_name": "operator",
            "summary": "Log final consume batch dispatch completed",
        },
    ]:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["current_phase"] == "consume-test"
    assert payload["current"]["phase"] == "consume-test"
    assert payload["current"]["agent_name"] == "vulnerability-analyst"
    assert payload["current"]["summary"] == "Processing 2 queued case(s)"
    assert any(item["phase"] == "consume-test" and item["state"] == "active" for item in payload["phases"])
    assert all(not (item["phase"] == "recon" and item["state"] == "active") for item in payload["phases"])



def test_run_summary_does_not_reactivate_completed_agents_from_surface_updates():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "target.example",
                "status": "in_progress",
                "phases_completed": ["recon", "collect"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )

    for event in [
        {
            "event_type": "task.completed",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon summary",
        },
        {
            "event_type": "surface.updated",
            "phase": "unknown",
            "task_name": "dynamic_render",
            "agent_name": "recon-specialist",
            "summary": "dynamic_render discovered: GET /web3/explorer",
        },
        {
            "event_type": "task.started",
            "phase": "consume-test",
            "task_name": "source-analyzer",
            "agent_name": "source-analyzer",
            "summary": "Source analysis start",
        },
    ]:
        response = client.post(
            f"/projects/{project['id']}/runs/{run['id']}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
        assert response.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["active_agents"] == 1
    assert payload["current"]["agent_name"] == "source-analyzer"
    recon_card = next(item for item in payload["agents"] if item["agent_name"] == "recon-specialist")
    assert recon_card["status"] == "completed"
    assert recon_card["phase"] == "recon"
    assert recon_card["task_name"] == "recon-specialist"
    assert recon_card["summary"] == "dynamic_render discovered: GET /web3/explorer"



def test_run_summary_prefers_live_exploit_phase_over_stale_scope_phase():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": [],
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )

    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "phase.started",
            "phase": "exploit",
            "task_name": "phase-transition",
            "agent_name": "operator",
            "summary": "Credential follow-up moved the run into exploit",
        },
    )
    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "exploit",
            "task_name": "exploit-developer",
            "agent_name": "exploit-developer",
            "summary": "Authenticated exploit verification",
        },
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["current_phase"] == "exploit"
    assert payload["current"]["phase"] == "exploit"
    assert any(item["phase"] == "exploit" and item["state"] == "active" for item in payload["phases"])
    assert all(not (item["phase"] == "recon" and item["state"] == "active") for item in payload["phases"])

    persisted_scope = json.loads((active_dir / "scope.json").read_text(encoding="utf-8"))
    assert persisted_scope["current_phase"] == "exploit"
    assert persisted_scope["phases_completed"] == ["recon", "collect", "consume_test"]


def test_run_summary_reopened_current_phase_prunes_completed_marker_and_stays_active():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": ["recon", "collect", "consume_test"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases (type, status, assigned_agent, source) VALUES ('api', 'processing', 'vulnerability-analyst', 'katana-xhr')"
        )
        connection.commit()

    client.post(
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

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    consume_phase = next(item for item in payload["phases"] if item["phase"] == "consume-test")
    assert consume_phase["state"] == "active"
    assert consume_phase["active_agents"] == 1
    assert payload["overview"]["current_phase"] == "consume-test"
    assert payload["current"]["phase"] == "consume-test"

    persisted_scope = json.loads((active_dir / "scope.json").read_text(encoding="utf-8"))
    assert persisted_scope["current_phase"] == "consume_test"
    assert persisted_scope["phases_completed"] == ["recon", "collect"]

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    consume_waterfall = next(item for item in run_metadata["phase_waterfall"] if item["phase"] == "consume-test")
    assert consume_waterfall["state"] == "active"
    assert consume_waterfall["active_agents"] == 1


def test_run_summary_reopens_consume_test_when_queue_remains_after_exploit_escalation():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "phases_completed": ["recon", "collect", "consume_test"],
                "current_phase": "exploit",
            }
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases (type, status, assigned_agent, source) VALUES ('api', 'processing', 'vulnerability-analyst', 'katana-xhr')"
        )
        connection.execute(
            "INSERT INTO cases (type, status, assigned_agent, source) VALUES ('api', 'pending', NULL, 'katana')"
        )
        connection.commit()

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": 1774848785415,
                        "part": {
                            "tool": "task",
                            "state": {
                                "status": "completed",
                                "input": {
                                    "description": "Exploit high findings",
                                    "subagent_type": "exploit-developer",
                                    "prompt": "Current phase: consume_test (escalated high findings)\n",
                                },
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": 1774848798572,
                        "part": {
                            "tool": "bash",
                            "title": "Fetch second API batch",
                            "state": {
                                "status": "completed",
                                "input": {
                                    "description": "Fetch second API batch",
                                    "command": "./scripts/dispatcher.sh stats",
                                },
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    consume_phase = next(item for item in payload["phases"] if item["phase"] == "consume-test")
    exploit_phase = next(item for item in payload["phases"] if item["phase"] == "exploit")
    assert payload["overview"]["current_phase"] == "consume-test"
    assert payload["current"]["phase"] == "consume-test"
    assert consume_phase["state"] == "active"
    assert exploit_phase["state"] == "pending"

    persisted_scope = json.loads((active_dir / "scope.json").read_text(encoding="utf-8"))
    assert persisted_scope["current_phase"] == "consume_test"
    assert persisted_scope["phases_completed"] == ["recon", "collect"]

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert run_metadata["current_phase"] == "consume-test"
    consume_agent = next(item for item in run_metadata["agents"] if item["agent_name"] == "vulnerability-analyst")
    assert consume_agent["status"] == "active"
    assert consume_agent["phase"] == "consume-test"


def test_run_summary_event_creation_updates_run_metadata_timestamp():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "recon"}),
        encoding="utf-8",
    )

    run_root = Path(run["engagement_root"])
    run_json = run_root / "run.json"
    before = json.loads(run_json.read_text(encoding="utf-8")).get("updated_at", "")
    time.sleep(1.1)

    event_response = client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon start",
        },
    )
    assert event_response.status_code == 201

    after = json.loads(run_json.read_text(encoding="utf-8"))["updated_at"]
    assert after
    assert after != before


def test_run_summary_prefers_workflow_activity_timestamp_over_stale_events():
    from app import db as app_db
    from app.db import database_path

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )
    (active_dir / "log.md").write_text("# log\n", encoding="utf-8")
    app_db.update_run_status(run["id"], "running")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    time.sleep(1.1)
    (active_dir / "log.md").write_text("# log\nupdated\n", encoding="utf-8")
    stat_mtime = (active_dir / "log.md").stat().st_mtime
    expected_utc = datetime.fromtimestamp(stat_mtime, UTC).strftime("%Y-%m-%d %H:%M:%S")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["overview"]["updated_at"] == expected_utc


def test_run_summary_syncs_run_metadata_updated_at_to_utc_workflow_activity(monkeypatch):
    from app import db as app_db
    from app.db import database_path

    monkeypatch.setattr("app.services.run_summary._reconcile_run_status", lambda current_run: current_run)

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )
    (active_dir / "log.md").write_text("# log\n", encoding="utf-8")
    app_db.update_run_status(run["id"], "running")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    time.sleep(1.1)
    (active_dir / "log.md").write_text("# log\nupdated\n", encoding="utf-8")
    stat_mtime = (active_dir / "log.md").stat().st_mtime
    expected_utc = datetime.fromtimestamp(stat_mtime, UTC).strftime("%Y-%m-%d %H:%M:%S")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert response.json()["overview"]["updated_at"] == expected_utc
    assert run_metadata["updated_at"] == expected_utc


def test_run_summary_syncs_run_metadata_updated_at_to_latest_event_when_newer_than_workflow_files(monkeypatch):
    from app import db as app_db
    from app.db import database_path

    monkeypatch.setattr("app.services.run_summary._reconcile_run_status", lambda current_run: current_run)

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )
    (active_dir / "log.md").write_text("# log\n", encoding="utf-8")
    app_db.update_run_status(run["id"], "running")

    stale_activity = datetime(2026, 3, 25, 0, 0, 0, tzinfo=UTC)
    stale_epoch = stale_activity.timestamp()
    for path in (active_dir / "scope.json", active_dir / "log.md"):
        os.utime(path, (stale_epoch, stale_epoch))

    time.sleep(1.1)
    late_event_at = datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.execute(
            "INSERT INTO events(run_id, event_type, phase, task_name, agent_name, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], "task.completed", "consume-test", "source-analyzer", "source-analyzer", "Late event", late_event_at),
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert response.json()["overview"]["updated_at"] == late_event_at
    assert run_metadata["updated_at"] == late_event_at



def test_run_summary_ignores_heartbeat_only_freshness_when_syncing_updated_at(monkeypatch):
    from app import db as app_db
    from app.db import database_path

    monkeypatch.setattr("app.services.run_summary._reconcile_run_status", lambda current_run: current_run)

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "hostname": "target.example",
                "status": "in_progress",
                "current_phase": "consume_test",
                "phases_completed": ["recon", "collect"],
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "log.md").write_text("# log\n", encoding="utf-8")
    app_db.update_run_status(run["id"], "running")

    stale_activity = datetime(2026, 3, 25, 0, 0, 0, tzinfo=UTC)
    stale_epoch = stale_activity.timestamp()
    for path in (active_dir / "scope.json", active_dir / "log.md"):
        os.utime(path, (stale_epoch, stale_epoch))

    substantive_event_at = "2026-03-25 00:00:30"
    heartbeat_event_at = datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE id = ?",
            (heartbeat_event_at, run["id"]),
        )
        connection.execute(
            "INSERT INTO events(run_id, event_type, phase, task_name, agent_name, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], "task.completed", "consume-test", "source-analyzer", "source-analyzer", "Substantive event", substantive_event_at),
        )
        connection.execute(
            "INSERT INTO events(run_id, event_type, phase, task_name, agent_name, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], "run.heartbeat", "consume-test", "runtime", "launcher", "Heartbeat only", heartbeat_event_at),
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert response.json()["overview"]["updated_at"] == substantive_event_at
    assert run_metadata["updated_at"] == substantive_event_at



def test_run_summary_repairs_future_skewed_run_updated_at_from_workflow_activity(monkeypatch):
    from app import db as app_db
    from app.db import database_path

    monkeypatch.setattr("app.services.run_summary._reconcile_run_status", lambda current_run: current_run)

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )
    (active_dir / "log.md").write_text("# log\nupdated\n", encoding="utf-8")
    app_db.update_run_status(run["id"], "running")

    recent_activity = datetime.now(UTC).replace(microsecond=0)
    recent_epoch = recent_activity.timestamp()
    for path in (active_dir / "scope.json", active_dir / "log.md"):
        os.utime(path, (recent_epoch, recent_epoch))

    future_skewed = (recent_activity + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE id = ?",
            (future_skewed, run["id"]),
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    expected_utc = recent_activity.strftime("%Y-%m-%d %H:%M:%S")
    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert response.json()["overview"]["updated_at"] == expected_utc
    assert run_metadata["updated_at"] == expected_utc



def test_run_summary_projects_current_state_into_run_metadata():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "recon"}),
        encoding="utf-8",
    )

    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon start",
        },
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    run_metadata = json.loads((Path(run["engagement_root"]) / "run.json").read_text(encoding="utf-8"))
    assert run_metadata["current_action"] == payload["current"]
    assert run_metadata["phase_waterfall"] == payload["phases"]
    assert run_metadata["agents"] == payload["agents"]
    assert run_metadata["current_phase"] == payload["overview"]["current_phase"]
    assert run_metadata["current_task"] == payload["current"]["task_name"]
    assert run_metadata["current_agent"] == payload["current"]["agent_name"]
    assert run_metadata["current_summary"] == payload["current"]["summary"]
    assert run_metadata["findings_count"] == payload["overview"]["findings_count"]
    assert run_metadata["active_agents"] == payload["overview"]["active_agents"]
    assert run_metadata["available_agents"] == payload["overview"]["available_agents"]
    assert run_metadata["current_action"]["summary"] == "Recon start"


def test_run_summary_handles_runtime_lookup_unavailable_without_failing(monkeypatch):
    from app import db as app_db
    from app.db import database_path
    from app.services.launcher import RUNTIME_PID_LOOKUP_UNAVAILABLE

    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "collect"}),
        encoding="utf-8",
    )
    app_db.update_run_status(run["id"], "running")

    with sqlite3.connect(database_path()) as connection:
        connection.execute(
            "UPDATE runs SET updated_at = '2026-03-25 00:00:00' WHERE id = ?",
            (run["id"],),
        )
        connection.commit()

    monkeypatch.setattr("app.services.runs.locate_runtime_pid", lambda _run: RUNTIME_PID_LOOKUP_UNAVAILABLE)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["overview"]["current_phase"] == "collect"


def test_run_summary_prefers_terminal_run_status_over_in_progress_scope():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )

    from app import db as app_db
    app_db.update_run_status(run["id"], "failed")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["status"] == "failed"


def test_run_summary_failed_terminal_run_clears_live_activity_and_uses_stop_reason():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)
    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://127.0.0.1:8000",
                "hostname": "127.0.0.1",
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )

    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "recon-specialist",
            "agent_name": "recon-specialist",
            "summary": "Recon specialist scan",
        },
    )
    client.post(
        f"/projects/{project['id']}/runs/{run['id']}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "task.started",
            "phase": "recon",
            "task_name": "source-analyzer",
            "agent_name": "source-analyzer",
            "summary": "Source analyzer review",
        },
    )

    from app import db as app_db
    app_db.update_run_status(run["id"], "failed")
    run_json = Path(run["engagement_root"]) / "run.json"
    metadata = json.loads(run_json.read_text(encoding="utf-8"))
    metadata["stop_reason_text"] = "target http://127.0.0.1:8000 was not listening; recon and source collection could not proceed"
    run_json.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["target"]["status"] == "failed"
    assert payload["overview"]["active_agents"] == 0
    assert payload["current"]["agent_name"] == ""
    assert payload["current"]["task_name"] == ""
    assert payload["current"]["summary"] == metadata["stop_reason_text"]
    assert all(agent["status"] != "active" for agent in payload["agents"])
    assert all(phase["active_agents"] == 0 for phase in payload["phases"])
    assert all(phase["state"] != "active" for phase in payload["phases"])


def test_run_summary_keeps_case_types_during_transient_sqlite_lock():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "collect"}),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT)")
        connection.executemany(
            "INSERT INTO cases (type, status, assigned_agent) VALUES (?, ?, ?)",
            [
                ("api", "done", None),
                ("api", "pending", None),
                ("page", "processing", "recon-specialist"),
            ],
        )
        connection.commit()

    def hold_lock() -> None:
        with sqlite3.connect(cases_db, timeout=1.0) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            time.sleep(0.35)
            connection.commit()

    locker = threading.Thread(target=hold_lock)
    locker.start()
    time.sleep(0.05)

    seen_non_empty = False
    for _ in range(4):
        response = client.get(
            f"/projects/{project['id']}/runs/{run['id']}/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        if payload["coverage"]["case_types"]:
            seen_non_empty = True
            assert any(item["type"] == "api" and item["total"] == 2 for item in payload["coverage"]["case_types"])
        time.sleep(0.1)

    locker.join()
    assert seen_non_empty


def test_run_summary_keeps_case_counts_when_processing_agent_aggregation_is_malformed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, method TEXT, url TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (type, status, assigned_agent, method, url, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("api", "done", None, "GET", "https://target.example/api/version", "katana"),
                ("api", "pending", None, "GET", "https://target.example/api/users", "katana-xhr"),
                ("javascript", "processing", "source-analyzer", "GET", "https://target.example/main.js", "katana"),
            ],
        )
        connection.commit()

    real_connect = sqlite3.connect

    class FaultyProcessingConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            if "SELECT assigned_agent, COUNT(*) AS count FROM cases WHERE status = 'processing'" in str(sql):
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
            return FaultyProcessingConnection(connection)
        return connection

    monkeypatch.setattr(run_summary.sqlite3, "connect", flaky_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["coverage"]["total_cases"] == 3
    assert payload["coverage"]["completed_cases"] == 1
    assert payload["coverage"]["pending_cases"] == 1
    assert payload["coverage"]["processing_cases"] == 1
    assert any(item["type"] == "api" and item["total"] == 2 for item in payload["coverage"]["case_types"])


def test_observed_paths_returns_complete_case_list():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "collect"}),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", "https://target.example/api/v1/users", "api", "done", "", "source-analyzer"),
                ("POST", "https://target.example/api/v1/login", "api", "processing", "vulnerability-analyst", "source-analyzer"),
                ("GET", "https://target.example/robots.txt", "data", "pending", "", "recon-specialist"),
            ],
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/observed-paths",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 3
    assert payload[0]["status"] == "processing"
    assert payload[0]["method"] == "POST"
    assert payload[0]["assigned_agent"] == "vulnerability-analyst"
    assert any(item["url"] == "https://target.example/api/v1/users" and item["type"] == "api" for item in payload)


def test_observed_paths_recovers_when_bulk_case_query_is_malformed(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "collect"}),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", "https://target.example/api/v1/users", "api", "done", "", "source-analyzer"),
                ("POST", "https://target.example/api/v1/login", "api", "processing", "vulnerability-analyst", "source-analyzer"),
                ("GET", "https://target.example/robots.txt", "data", "pending", "", "recon-specialist"),
            ],
        )
        connection.commit()

    real_connect = sqlite3.connect

    class FaultyObservedPathsConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            query = str(sql)
            if query.startswith("SELECT method, url, type, status, assigned_agent, source FROM cases ORDER BY"):
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
            return FaultyObservedPathsConnection(connection)
        return connection

    monkeypatch.setattr(run_summary.sqlite3, "connect", flaky_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/observed-paths",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 3
    assert payload[0]["status"] == "processing"
    assert payload[0]["method"] == "POST"
    assert payload[0]["assigned_agent"] == "vulnerability-analyst"
    assert any(item["url"] == "https://target.example/api/v1/users" and item["type"] == "api" for item in payload)


def test_run_summary_prefers_populated_cases_db_when_workspace_db_is_empty():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "127.0.0.1", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )

    workspace_db = Path(run["engagement_root"], "workspace", "cases.db")
    with sqlite3.connect(workspace_db) as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT)")
        connection.commit()

    active_db = active_dir / "cases.db"
    with sqlite3.connect(active_db) as connection:
        connection.execute("CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)")
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", "http://127.0.0.1:8000/api/products", "api", "done", "", "katana"),
                ("GET", "http://127.0.0.1:8000/rest/products", "api", "processing", "vulnerability-analyst", "katana"),
            ],
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["total_cases"] == 2
    assert payload["coverage"]["processing_cases"] == 1
    assert any(item["type"] == "api" and item["total"] == 2 for item in payload["coverage"]["case_types"])


def test_run_summary_process_log_projection_keeps_finished_tasks_out_of_active_state():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "port": 443,
                "scope": ["target.example"],
                "status": "in_progress",
                "start_time": "2026-03-25T08:00:00Z",
                "phases_completed": ["recon", "collect"],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL)")
        connection.execute("INSERT INTO cases (type, status) VALUES ('api', 'done')")
        connection.commit()

    runtime_dir = Path(run["engagement_root"]) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "process.log").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": 1774737501655,
                        "part": {
                            "tool": "bash",
                            "title": "Logs exploit validation dispatch",
                            "state": {
                                "status": "completed",
                                "input": {"description": "Logs exploit validation dispatch"},
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": 1774737501707,
                        "part": {
                            "tool": "task",
                            "state": {
                                "status": "completed",
                                "input": {
                                    "description": "Validate medium IDOR finding",
                                    "subagent_type": "exploit-developer",
                                    "prompt": "**Phase**: consume_test\n",
                                },
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["overview"]["active_agents"] == 0
    exploit_card = next(card for card in payload["agents"] if card["agent_name"] == "exploit-developer")
    operator_card = next(card for card in payload["agents"] if card["agent_name"] == "operator")
    assert exploit_card["status"] == "completed"
    assert operator_card["status"] == "completed"
    assert payload["current"]["agent_name"] == "exploit-developer"
    assert payload["current"]["summary"] == "Validate medium IDOR finding completed"


def test_observed_paths_prefers_populated_cases_db_when_workspace_db_is_empty():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "127.0.0.1", "status": "in_progress", "current_phase": "collect"}),
        encoding="utf-8",
    )

    workspace_db = Path(run["engagement_root"], "workspace", "cases.db")
    with sqlite3.connect(workspace_db) as connection:
        connection.execute("CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)")
        connection.commit()

    active_db = active_dir / "cases.db"
    with sqlite3.connect(active_db) as connection:
        connection.execute("CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)")
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("POST", "http://127.0.0.1:8000/rest/user/login", "api", "processing", "vulnerability-analyst", "katana-xhr"),
                ("GET", "http://127.0.0.1:8000/robots.txt", "data", "pending", "", "recon-specialist"),
            ],
        )
        connection.commit()

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/observed-paths",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 2
    assert payload[0]["url"] == "http://127.0.0.1:8000/rest/user/login"
    assert payload[0]["status"] == "processing"
    assert any(item["url"] == "http://127.0.0.1:8000/robots.txt" for item in payload)



def test_observed_paths_retries_suspiciously_empty_live_reads_with_snapshot(monkeypatch):
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps({"hostname": "target.example", "status": "in_progress", "current_phase": "consume_test"}),
        encoding="utf-8",
    )

    cases_db = active_dir / "cases.db"
    with sqlite3.connect(cases_db) as connection:
        connection.execute(
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.executemany(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GET", f"https://target.example/api/{index}", "api", "pending", "", "katana")
                for index in range(240)
            ],
        )
        connection.commit()

    assert cases_db.stat().st_size >= 16384

    empty_db = active_dir / "empty-live-observed.db"
    with sqlite3.connect(empty_db) as connection:
        connection.execute(
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.commit()

    real_connect = sqlite3.connect

    def empty_live_connect(database, *args, **kwargs):
        if str(database) == str(cases_db) and not kwargs.get("uri", False):
            return real_connect(empty_db, *args, **kwargs)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(run_summary.sqlite3, "connect", empty_live_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/observed-paths",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 240
    assert payload[0]["url"] == "https://target.example/api/0"
    assert payload[0]["source"] == "katana"


def test_run_summary_normalizes_loopback_runtime_artifacts_and_redacts_katana_headers():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "findings.md").write_text(
        "# Penetration Test Report: http://host.docker.internal:8000\n\n**Target**: http://host.docker.internal:8000\n",
        encoding="utf-8",
    )
    (active_dir / "report.md").write_text(
        "# Penetration Test Report: http://host.docker.internal:8000\n",
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text(
        '{"surface_type":"dynamic_render","target":"GET http://host.docker.internal:8000/rest/admin","source":"source-analyzer","rationale":"local runtime alias leaked"}\n',
        encoding="utf-8",
    )
    scans_dir = active_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)
    original_katana_text = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/"},
            "response": {
                "headers": {"Content-Type": "text/html"},
                "xhr_requests": [
                    {
                        "method": "GET",
                        "endpoint": "http://host.docker.internal:8000/rest/admin/application-version",
                        "headers": {
                            "Authorization": "Bearer secret-jwt",
                            "Cookie": "sid=secret-cookie",
                            "Accept": "application/json",
                        },
                    }
                ],
            },
        },
        separators=(",", ":"),
    )
    (scans_dir / "katana_output.jsonl").write_text(original_katana_text, encoding="utf-8")

    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
        )
        connection.execute(
            "INSERT INTO cases (method, url, type, status, assigned_agent, source) VALUES (?, ?, ?, ?, ?, ?)",
            ("GET", "http://host.docker.internal:8000/rest/admin", "api", "processing", "vulnerability-analyst", "katana"),
        )
        connection.commit()

    summary_response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["target"]["target"] == "http://127.0.0.1:8000"
    assert summary_payload["target"]["hostname"] == "127.0.0.1"
    assert summary_payload["target"]["scope_entries"] == ["127.0.0.1", "*.127.0.0.1"]

    observed_response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/observed-paths",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert observed_response.status_code == 200
    observed_payload = observed_response.json()
    assert observed_payload[0]["url"] == "http://127.0.0.1:8000/rest/admin"

    normalized_scope = json.loads((active_dir / "scope.json").read_text(encoding="utf-8"))
    assert normalized_scope["target"] == "http://host.docker.internal:8000"
    assert normalized_scope["hostname"] == "host.docker.internal"
    assert normalized_scope["scope"] == ["host.docker.internal", "*.host.docker.internal"]

    with sqlite3.connect(active_dir / "cases.db") as connection:
        row = connection.execute("SELECT url FROM cases").fetchone()
    assert row == ("http://host.docker.internal:8000/rest/admin",)

    findings_text = (active_dir / "findings.md").read_text(encoding="utf-8")
    report_text = (active_dir / "report.md").read_text(encoding="utf-8")
    surfaces_text = (active_dir / "surfaces.jsonl").read_text(encoding="utf-8")
    katana_text = (scans_dir / "katana_output.jsonl").read_text(encoding="utf-8")

    assert "host.docker.internal" not in findings_text
    assert "host.docker.internal" not in report_text
    assert "host.docker.internal" not in surfaces_text
    assert katana_text != original_katana_text
    assert "host.docker.internal" not in katana_text
    assert "secret-jwt" not in katana_text
    assert "secret-cookie" not in katana_text
    assert '<redacted>' in katana_text

    katana_rows = [json.loads(line) for line in katana_text.splitlines() if line.strip()]
    assert katana_rows[0]["request"]["endpoint"] == "http://127.0.0.1:8000/"
    xhr_headers = katana_rows[0]["response"]["xhr_requests"][0]["headers"]
    assert xhr_headers["Authorization"] == "<redacted>"
    assert xhr_headers["Cookie"] == "<redacted>"


def test_run_summary_redacts_live_katana_headers_for_non_loopback_runs():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://www.example.com")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://www.example.com",
                "hostname": "www.example.com",
                "port": 443,
                "scope": ["www.example.com", "*.www.example.com"],
                "status": "in_progress",
                "current_phase": "collect",
            }
        ),
        encoding="utf-8",
    )
    scans_dir = active_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)
    original_katana_text = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "https://www.example.com/"},
            "response": {
                "status_code": 200,
                "headers": {"Content-Type": "text/html"},
                "xhr_requests": [
                    {
                        "method": "GET",
                        "endpoint": "https://www.example.com/api/v5/account/balance",
                        "headers": {
                            "Cookie": "session=secret-cookie",
                            "X-API-Key": "secret-api-key",
                            "Accept": "application/json",
                        },
                    }
                ],
            },
        },
        separators=(",", ":"),
    )
    (scans_dir / "katana_output.jsonl").write_text(original_katana_text, encoding="utf-8")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    katana_text = (scans_dir / "katana_output.jsonl").read_text(encoding="utf-8")
    assert "secret-cookie" not in katana_text
    assert "secret-api-key" not in katana_text
    assert "<redacted>" in katana_text
    assert "https://www.example.com/api/v5/account/balance" in katana_text

    katana_rows = [json.loads(line) for line in katana_text.splitlines() if line.strip()]
    xhr_headers = katana_rows[0]["response"]["xhr_requests"][0]["headers"]
    assert xhr_headers["Cookie"] == "<redacted>"
    assert xhr_headers["X-API-Key"] == "<redacted>"
    assert xhr_headers["Accept"] == "application/json"


def test_run_summary_normalizes_malformed_katana_jsonl_streams_for_terminal_runs():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    scans_dir = active_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)

    first = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/"},
            "response": {
                "headers": {"Content-Type": "text/html"},
                "xhr_requests": [
                    {
                        "method": "GET",
                        "endpoint": "http://host.docker.internal:8000/rest/admin/application-version",
                        "headers": {
                            "Authorization": "Bearer secret-jwt",
                            "Cookie": "sid=secret-cookie",
                        },
                    }
                ],
            },
        },
        separators=(",", ":"),
    )
    second = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/main.js"},
            "response": {
                "headers": {
                    "Feature-Policy": "payment 'self'",
                    "Content-Type": "application/javascript; charset=UTF-8",
                }
            },
        },
        separators=(",", ":"),
    )
    third = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/rest/user/login"},
            "response": {
                "status_code": 200,
                "headers": {"Content-Type": "application/json"},
            },
        },
        separators=(",", ":"),
    )
    malformed_second = second.replace("Feature-Policy", f"Feature-Policy{chr(0)}").replace("payment 'self'", f"pa{chr(0)}yment 'self'")
    (scans_dir / "katana_output.jsonl").write_text(first + third + "\n" + malformed_second + "\n", encoding="utf-8")

    from app import db as app_db

    app_db.update_run_status(run["id"], "completed")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    normalized = (scans_dir / "katana_output.jsonl").read_text(encoding="utf-8")
    assert "\x00" not in normalized
    assert "host.docker.internal" not in normalized
    assert "secret-jwt" not in normalized
    assert "secret-cookie" not in normalized
    assert "<redacted>" in normalized

    rows = [json.loads(line) for line in normalized.splitlines() if line.strip()]
    assert len(rows) == 3
    assert rows[0]["request"]["endpoint"] == "http://127.0.0.1:8000/"
    assert rows[1]["request"]["endpoint"] == "http://127.0.0.1:8000/rest/user/login"
    assert rows[2]["request"]["endpoint"] == "http://127.0.0.1:8000/main.js"
    xhr_headers = rows[0]["response"]["xhr_requests"][0]["headers"]
    assert xhr_headers["Authorization"] == "<redacted>"
    assert xhr_headers["Cookie"] == "<redacted>"
    assert rows[2]["response"]["headers"]["Feature-Policy"] == "payment 'self'"



def test_run_summary_drops_irrecoverable_malformed_katana_jsonl_lines_for_terminal_runs():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    scans_dir = active_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)

    first = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/"},
            "response": {"status_code": 200, "headers": {"Content-Type": "text/html"}},
        },
        separators=(",", ":"),
    )
    second = json.dumps(
        {
            "request": {"method": "GET", "endpoint": "http://host.docker.internal:8000/rest/user/login"},
            "response": {"status_code": 200, "headers": {"Content-Type": "application/json"}},
        },
        separators=(",", ":"),
    )
    malformed = '{"request":{"method":"GET","endpoint":"http://host.docker.internal:8000/rest/continue-code","attribu//127.0.0.1:8000/main.jdocker.internal:8000/main.js"},"response":{"status_co'
    suffix_fragment = ':37 GMT"},"content_length":821}}'
    (scans_dir / "katana_output.jsonl").write_text(
        first + "\n" + malformed + "\n" + second + "\n" + suffix_fragment + "\n",
        encoding="utf-8",
    )

    from app import db as app_db

    app_db.update_run_status(run["id"], "completed")

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    normalized = (scans_dir / "katana_output.jsonl").read_text(encoding="utf-8")
    assert "host.docker.internal" not in normalized
    assert "attribu//127.0.0.1:8000/main.jdocker.internal:8000/main.js" not in normalized
    assert ':37 GMT"},"content_length":821}}' not in normalized

    rows = [json.loads(line) for line in normalized.splitlines() if line.strip()]
    assert len(rows) == 2
    assert [row["request"]["endpoint"] for row in rows] == [
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/rest/user/login",
    ]



def test_run_summary_backfills_surface_candidates_from_process_log_without_duplicates():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "port": 443,
                "scope": ["target.example", "*.target.example"],
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[source-analyzer] #### Surface Candidates\n"
                            "[source-analyzer] {\"surface_type\":\"account_recovery\",\"target\":\"GET /rest/user/security-question?email=... + POST /rest/user/reset-password\",\"source\":\"source-analyzer\",\"rationale\":\"bundle implements recover-by-email security-question lookup and password reset flow\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "[source-analyzer] {\"surface_type\":\"workflow_token\",\"target\":\"2FA tmpToken -> /2fa/enter\",\"source\":\"source-analyzer\",\"rationale\":\"login handler stores tmpToken before redirecting into the MFA workflow\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[source-analyzer] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    for _ in range(2):
        response = client.get(
            f"/projects/{project['id']}/runs/{run['id']}/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 2
    assert any(item["type"] == "account_recovery" and item["count"] == 1 for item in payload["coverage"]["surface_types"])
    assert any(item["type"] == "workflow_token" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(surfaces_rows) == 2
    assert {row["surface_type"] for row in surfaces_rows} == {"account_recovery", "workflow_token"}


def test_run_summary_backfill_normalizes_spa_route_surface_candidates_to_dynamic_render():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "start_time": "2026-03-29T23:59:38Z",
                "phases_completed": [],
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[vulnerability-analyst] #### Surface Candidates\n"
                            "[vulnerability-analyst] {\"surface_type\":\"spa_route\",\"target\":\"/#/score-board\",\"source\":\"vulnerability-analyst\",\"rationale\":\"referenced in application configuration\",\"evidence_ref\":\"/rest/admin/application-configuration\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[vulnerability-analyst] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 1
    assert any(item["type"] == "dynamic_render" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert surfaces_rows == [
        {
            "surface_type": "dynamic_render",
            "target": "/#/score-board",
            "source": "vulnerability-analyst",
            "rationale": "referenced in application configuration",
            "evidence_ref": "/rest/admin/application-configuration",
            "status": "discovered",
        }
    ]


def test_run_summary_backfill_accepts_category_and_path_surface_candidates():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[source-analyzer] #### Surface Candidates\n"
                            "[source-analyzer] {\"category\":\"auth_entry\",\"path\":\"/rest/user/login\",\"method\":\"POST\",\"source\":\"source-analyzer\",\"rationale\":\"main.js exposes login flow and hardcoded test credentials in the login component\",\"priority\":\"high\"}\n"
                            "[source-analyzer] {\"category\":\"dynamic_render\",\"url_or_pattern\":\"http://host.docker.internal:8000/#/web3-sandbox\",\"source\":\"source-analyzer\",\"reason\":\"lazy-loaded web3 sandbox compiles Solidity client-side\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[source-analyzer] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 2
    assert any(item["type"] == "auth_entry" and item["count"] == 1 for item in payload["coverage"]["surface_types"])
    assert any(item["type"] == "dynamic_render" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert surfaces_rows == [
        {
            "surface_type": "auth_entry",
            "target": "POST /rest/user/login",
            "source": "source-analyzer",
            "rationale": "main.js exposes login flow and hardcoded test credentials in the login component",
            "evidence_ref": "",
            "status": "discovered",
        },
        {
            "surface_type": "dynamic_render",
            "target": "GET http://127.0.0.1:8000/#/web3-sandbox",
            "source": "source-analyzer",
            "rationale": "lazy-loaded web3 sandbox compiles Solidity client-side",
            "evidence_ref": "",
            "status": "discovered",
        },
    ]


def test_run_summary_backfill_accepts_new_surface_taxonomy_entries():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://www.example.com")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://www.example.com",
                "hostname": "www.example.com",
                "port": 443,
                "scope": ["www.example.com", "*.example.com"],
                "status": "in_progress",
                "current_phase": "consume_test",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[vulnerability-analyst] #### Surface Candidates\n"
                            "[vulnerability-analyst] {\"surface_type\":\"api_param_followup\",\"target\":\"GET https://www.example.com/priapi/v1/dx/market/v2/token/pool/project/list :: chainId\",\"source\":\"vulnerability-analyst\",\"rationale\":\"Endpoint explicitly requires Integer chainId; concrete input missing in current batch\",\"evidence_ref\":\"scans/va-api-batch/summary.json\",\"status\":\"discovered\"}\n"
                            "[vulnerability-analyst] {\"surface_type\":\"cors_review\",\"target\":\"GET https://www.example.com/v3/users/support/common/list-download-url\",\"source\":\"vulnerability-analyst\",\"rationale\":\"Reflected arbitrary Origin in ACAO on unauthenticated public endpoint; low-impact weak signal only\",\"evidence_ref\":\"scans/va-api-batch/summary.json\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[vulnerability-analyst] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 2
    assert any(item["type"] == "api_param_followup" and item["count"] == 1 for item in payload["coverage"]["surface_types"])
    assert any(item["type"] == "cors_review" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert surfaces_rows == [
        {
            "surface_type": "api_param_followup",
            "target": "GET https://www.example.com/priapi/v1/dx/market/v2/token/pool/project/list :: chainId",
            "source": "vulnerability-analyst",
            "rationale": "Endpoint explicitly requires Integer chainId; concrete input missing in current batch",
            "evidence_ref": "scans/va-api-batch/summary.json",
            "status": "discovered",
        },
        {
            "surface_type": "cors_review",
            "target": "GET https://www.example.com/v3/users/support/common/list-download-url",
            "source": "vulnerability-analyst",
            "rationale": "Reflected arbitrary Origin in ACAO on unauthenticated public endpoint; low-impact weak signal only",
            "evidence_ref": "scans/va-api-batch/summary.json",
            "status": "discovered",
        },
    ]


def test_run_summary_backfill_normalizes_loopback_surface_candidates_without_duplicate_growth():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "http://127.0.0.1:8000")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "http://host.docker.internal:8000",
                "hostname": "host.docker.internal",
                "port": 8000,
                "scope": ["host.docker.internal", "*.host.docker.internal"],
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[source-analyzer] #### Surface Candidates\n"
                            "[source-analyzer] {\"surface_type\":\"auth_entry\",\"target\":\"GET http://host.docker.internal:8000/#/login\",\"source\":\"source-analyzer\",\"rationale\":\"login route discovered from SPA bundle\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[source-analyzer] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    for _ in range(3):
        response = client.get(
            f"/projects/{project['id']}/runs/{run['id']}/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 1
    assert any(item["type"] == "auth_entry" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(surfaces_rows) == 1
    assert surfaces_rows[0]["target"] == "GET http://127.0.0.1:8000/#/login"
    assert "host.docker.internal" not in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8")


def test_run_summary_backfill_preserves_mixed_surface_candidates_by_normalizing_placeholders():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "port": 443,
                "scope": ["target.example", "*.target.example"],
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[source-analyzer] #### Surface Candidates\n"
                            "[source-analyzer] {\"surface_type\":\"account_recovery\",\"target\":\"POST /rest/user/reset-password and GET /rest/user/security-question?email=<email>\",\"source\":\"source-analyzer\",\"rationale\":\"bundle implements recover-by-email security-question lookup and password reset flow\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[source-analyzer] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 1
    assert any(item["type"] == "account_recovery" and item["count"] == 1 for item in payload["coverage"]["surface_types"])

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert surfaces_rows == [
        {
            "surface_type": "account_recovery",
            "target": "POST /rest/user/reset-password and GET /rest/user/security-question?email=...",
            "source": "source-analyzer",
            "rationale": "bundle implements recover-by-email security-question lookup and password reset flow",
            "evidence_ref": "main.js",
            "status": "discovered",
        }
    ]


def test_run_summary_backfill_skips_placeholder_surface_candidates():
    client = TestClient(app)
    token = register_and_login(client, "alice")
    project = create_project(client, token)
    run = create_run(client, token, project["id"], "https://target.example")
    active_dir = setup_active_engagement(run)

    (active_dir / "scope.json").write_text(
        json.dumps(
            {
                "target": "https://target.example",
                "hostname": "target.example",
                "port": 443,
                "scope": ["target.example", "*.target.example"],
                "status": "in_progress",
                "current_phase": "recon",
            }
        ),
        encoding="utf-8",
    )
    (active_dir / "surfaces.jsonl").write_text("", encoding="utf-8")

    process_log = Path(run["engagement_root"], "runtime", "process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    process_log.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "output": (
                            "[source-analyzer] #### Surface Candidates\n"
                            "[source-analyzer] {\"surface_type\":\"workflow_token\",\"target\":\"GET /rest/continue-code/apply/<code>\",\"source\":\"source-analyzer\",\"rationale\":\"templated continue-code route\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "[source-analyzer] {\"surface_type\":\"account_recovery\",\"target\":\"GET /rest/user/security-question?email=<email>\",\"source\":\"source-analyzer\",\"rationale\":\"templated account recovery route\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "[source-analyzer] {\"surface_type\":\"auth_entry\",\"target\":\"GET /login\",\"source\":\"source-analyzer\",\"rationale\":\"concrete login route\",\"evidence_ref\":\"main.js\",\"status\":\"discovered\"}\n"
                            "\n"
                            "[source-analyzer] #### Findings\n"
                        )
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["total_surfaces"] == 1
    assert payload["coverage"]["surface_types"] == [
        {
            "type": "auth_entry",
            "total": None,
            "done": None,
            "pending": None,
            "processing": None,
            "error": None,
            "count": 1,
        }
    ]

    surfaces_rows = [json.loads(line) for line in (active_dir / "surfaces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert surfaces_rows == [
        {
            "surface_type": "auth_entry",
            "target": "GET /login",
            "source": "source-analyzer",
            "rationale": "concrete login route",
            "evidence_ref": "main.js",
            "status": "discovered",
        }
    ]
