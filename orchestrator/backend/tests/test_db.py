import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
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


def setup_active_engagement(run: dict) -> Path:
    workspace = Path(run["engagement_root"], "workspace")
    engagements = workspace / "engagements"
    active_name = "2026-03-25-000000-example"
    active_dir = engagements / active_name
    active_dir.mkdir(parents=True, exist_ok=True)
    (engagements / ".active").write_text(f"engagements/{active_name}", encoding="utf-8")
    return active_dir


def test_summary_endpoint_retries_transient_db_open_error_during_auth(monkeypatch):
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
                "current_phase": "collect",
            }
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(active_dir / "cases.db") as connection:
        connection.execute("CREATE TABLE cases (type TEXT NOT NULL, status TEXT NOT NULL)")
        connection.execute("INSERT INTO cases (type, status) VALUES ('page', 'pending')")
        connection.commit()

    original_connect = db.sqlite3.connect
    attempts = {"remaining": 1}
    db_path = db.database_path()

    def flaky_connect(target, *args, **kwargs):
        candidate = Path(target) if not isinstance(target, Path) else target
        if attempts["remaining"] and candidate == db_path:
            attempts["remaining"] -= 1
            raise sqlite3.OperationalError("unable to open database file")
        return original_connect(target, *args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", flaky_connect)

    response = client.get(
        f"/projects/{project['id']}/runs/{run['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["overview"]["current_phase"] == "collect"
    assert attempts["remaining"] == 0


def test_connection_uses_wal_mode():
    from app import db
    db.init_db()
    with db.get_connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert mode.lower() == "wal"
    assert busy >= 5000
    assert sync == 1  # NORMAL
    assert fk == 1


def test_concurrent_inserts_do_not_deadlock(tmp_path):
    """10 threads x 20 inserts each complete under 5s with WAL."""
    import threading, time
    from app import db
    db.init_db()
    user = db.create_user("cc_user", "ph", "s")
    proj = db.create_project(
        user_id=user.id, name="cc", slug="cc", root_path=str(tmp_path),
    )
    run = db.create_run(
        project_id=proj.id, target="http://x", status="running",
        engagement_root=str(tmp_path),
    )

    errors = []
    def worker(tid):
        try:
            for i in range(20):
                db.create_event(run.id, "task.status", "consume", f"t{tid}", "vuln", f"i{i}")
        except Exception as e:
            errors.append(e)

    start = time.time()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    elapsed = time.time() - start

    assert errors == []
    assert elapsed < 5.0
    with db.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?", (run.id,)
        ).fetchone()[0]
    assert count == 200
