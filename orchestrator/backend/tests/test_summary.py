import json
import sqlite3
import threading
import time
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
            "CREATE TABLE cases (method TEXT, url TEXT, type TEXT NOT NULL, status TEXT NOT NULL, assigned_agent TEXT, source TEXT)"
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
