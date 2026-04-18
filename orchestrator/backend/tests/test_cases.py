from fastapi.testclient import TestClient
from app.main import app
from app import db


def _register(client, username="alice"):
    client.post("/auth/register", json={"username": username, "password": "secret-password"})
    return client.post("/auth/login",
                       json={"username": username, "password": "secret-password"}).json()["access_token"]


def _setup(client, username, isolate_data_dir):
    token = _register(client, username)
    user = db.get_user_by_username(username)
    proj = db.create_project(user_id=user.id, name=username, slug=username,
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x", status="running",
                        engagement_root=str(isolate_data_dir))
    return token, proj, run


def test_list_cases_returns_all(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "a_c4", isolate_data_dir)
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/a", state="done")
    db.upsert_case(case_id=2, run_id=run.id, method="POST", path="/b",
                   state="finding", finding_id="F-1")
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert [c["case_id"] for c in r.json()] == [1, 2]
    assert r.json()[1]["finding_id"] == "F-1"


def test_list_cases_filter_state(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "b_c4", isolate_data_dir)
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/a", state="done")
    db.upsert_case(case_id=2, run_id=run.id, method="GET", path="/b", state="finding")
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases?state=finding",
                   headers={"Authorization": f"Bearer {token}"})
    assert [c["case_id"] for c in r.json()] == [2]


def test_list_cases_filter_method(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "m_c4", isolate_data_dir)
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/a", state="done")
    db.upsert_case(case_id=2, run_id=run.id, method="POST", path="/b", state="done")
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases?method=POST",
                   headers={"Authorization": f"Bearer {token}"})
    assert [c["case_id"] for c in r.json()] == [2]


def test_list_cases_filter_category(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "cat_c4", isolate_data_dir)
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/a",
                   category="injection", state="done")
    db.upsert_case(case_id=2, run_id=run.id, method="GET", path="/b",
                   category="auth", state="done")
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases?category=injection",
                   headers={"Authorization": f"Bearer {token}"})
    assert [c["case_id"] for c in r.json()] == [1]


def test_get_case_detail(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "c_c4", isolate_data_dir)
    db.upsert_case(case_id=32, run_id=run.id, method="GET", path="/api/search",
                   category="injection", state="finding", finding_id="F-3",
                   result="SQLi", started_at=1, finished_at=13)
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/32",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == 32
    assert body["finding_id"] == "F-3"
    assert body["duration_ms"] == 12000  # (13 - 1) * 1000


def test_get_case_detail_missing_timestamps_duration_none(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "d_c4", isolate_data_dir)
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/a", state="queued")
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/1",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.json()["duration_ms"] is None


def test_get_case_404(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "e_c4", isolate_data_dir)
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/999",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_list_cases_falls_back_to_agent_cases_db(isolate_data_dir):
    """Bug 4: when the structured cases table is empty, /cases must fall back to
    reading from the agent's cases.db so historical runs are not blank."""
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "fb_c4", isolate_data_dir)

    # Structured cases table is empty (no upsert_case calls).
    # Create a realistic agent cases.db with two rows.
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-fb"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"collect"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-fb")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO cases (id, method, url, type, status) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "GET",  "/api/users",    "api",  "done"),
                (2, "POST", "/api/login",    "auth", "pending"),
            ],
        )
        conn.commit()

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 2
    paths = {c["path"] for c in cases}
    assert "/api/users" in paths
    assert "/api/login" in paths
    # State mapping: "done" → "done", "pending" → "queued"
    states = {c["path"]: c["state"] for c in cases}
    assert states["/api/users"] == "done"
    assert states["/api/login"] == "queued"


def test_get_case_detail_falls_back_to_agent_cases_db(isolate_data_dir):
    """Bug fix: GET /cases/:id must fall back to cases.db when the structured
    cases table is empty, so clicking a row shown by list_cases doesn't 404."""
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "gc_fb_c4", isolate_data_dir)

    # Structured cases table is empty.
    # Create a realistic agent cases.db with two rows.
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-gc-fb"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"collect"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-gc-fb")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO cases (id, method, url, type, status) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "GET",  "/api/users",  "api",  "done"),
                (2, "POST", "/api/login",  "auth", "pending"),
            ],
        )
        conn.commit()

    # GET /cases/1 must return the row from cases.db.
    r1 = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/1",
                    headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["case_id"] == 1
    assert body1["path"] == "/api/users"
    assert body1["state"] == "done"

    # GET /cases/2 must return the row from cases.db (state mapped from "pending").
    r2 = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/2",
                    headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["case_id"] == 2
    assert body2["path"] == "/api/login"
    assert body2["state"] == "queued"

    # A case id not in cases.db must still 404.
    r_missing = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/99",
                           headers={"Authorization": f"Bearer {token}"})
    assert r_missing.status_code == 404


def test_cases_rejects_other_users_run(isolate_data_dir):
    client = TestClient(app)
    _register(client, "alice_c4")
    eve_token = _register(client, "eve_c4")
    alice_user = db.get_user_by_username("alice_c4")
    alice_proj = db.create_project(user_id=alice_user.id, name="ap", slug="ap_c4",
                                   root_path=str(isolate_data_dir))
    alice_run = db.create_run(project_id=alice_proj.id, target="http://x",
                              status="running", engagement_root=str(isolate_data_dir))
    r = client.get(f"/projects/{alice_proj.id}/runs/{alice_run.id}/cases",
                   headers={"Authorization": f"Bearer {eve_token}"})
    assert r.status_code == 404
