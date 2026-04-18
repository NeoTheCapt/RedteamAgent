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


def test_list_cases_merges_structured_and_agent_db(isolate_data_dir):
    """Bug 1: partial structured rows must be merged with authoritative cases.db.

    Scenario:
    - Structured table has 2 rows (case_id=1, case_id=2) with rich metadata.
    - Agent cases.db has 3 rows (id=1, id=2, id=3).
    - GET /cases must return 3 rows; rows 1 and 2 must carry structured metadata
      (started_at, finished_at, duration_ms); row 3 comes from cases.db only.
    """
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "mg_c4", isolate_data_dir)

    # Insert 2 structured rows with full metadata.
    db.upsert_case(case_id=1, run_id=run.id, method="GET", path="/api/a",
                   state="done", started_at=1000, finished_at=2000)
    db.upsert_case(case_id=2, run_id=run.id, method="POST", path="/api/b",
                   state="running", started_at=3000, finished_at=None)

    # Create agent cases.db with 3 rows (id=1 and 2 overlap; id=3 is db-only).
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-mg"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"collect"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-mg")

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
                (1, "GET",  "/api/a",  "api",  "done"),
                (2, "POST", "/api/b",  "api",  "processing"),
                (3, "GET",  "/api/c",  "api",  "pending"),
            ],
        )
        conn.commit()

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cases = r.json()

    # All 3 cases must appear.
    assert len(cases) == 3
    by_id = {c["case_id"]: c for c in cases}
    assert set(by_id.keys()) == {1, 2, 3}

    # Structured wins for case_id=1: has duration_ms from started_at/finished_at.
    assert by_id[1]["duration_ms"] == (2000 - 1000) * 1000
    assert by_id[1]["path"] == "/api/a"

    # Structured wins for case_id=2: started_at present, finished_at None → no duration.
    assert by_id[2]["started_at"] == 3000
    assert by_id[2]["duration_ms"] is None

    # case_id=3 comes from cases.db only.
    assert by_id[3]["path"] == "/api/c"
    assert by_id[3]["state"] == "queued"  # mapped from "pending"
    assert by_id[3]["duration_ms"] is None


def test_list_cases_wal_fallback_used(isolate_data_dir, monkeypatch):
    """Bug 2: cases.py must use _read_sqlite_with_fallback, not bare sqlite3.connect.

    Verify that _read_sqlite_with_fallback is called (rather than a bare
    sqlite3.connect) by confirming the helper is used in the code path.
    """
    import sqlite3 as _sqlite3
    from unittest.mock import patch, MagicMock

    client = TestClient(app)
    token, proj, run = _setup(client, "wal_c4", isolate_data_dir)

    # Create a cases.db file so the path resolves.
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-wal"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"collect"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-wal")

    cases_db_path = eng_dir / "cases.db"
    with _sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.execute("INSERT INTO cases VALUES (1,'GET','/x','api','done')")
        conn.commit()

    call_count = []

    import app.api.cases as cases_module
    original = cases_module._read_sqlite_with_fallback

    def tracking_fallback(path, reader, default):
        call_count.append(path)
        return original(path, reader, default)

    with patch.object(cases_module, "_read_sqlite_with_fallback", side_effect=tracking_fallback):
        r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                       headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    # _read_sqlite_with_fallback must have been called at least once (for the
    # cases.db read path in _read_cases_from_agent_db).
    assert len(call_count) >= 1


def test_list_cases_per_field_merge_preserves_route_from_cases_db_when_structured_has_blank_fields(isolate_data_dir):
    """Bug 1: out-of-order case_done-before-dispatch_start regression.

    When case_done arrives before dispatch_start, event_apply creates a
    structured row with method='' and path=''.  The per-field merge must
    NOT overwrite the real route data already present in cases.db.
    Both GET /cases and GET /cases/:id must return the real method/path.
    """
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "ooo_c4", isolate_data_dir)

    # Simulate the out-of-order scenario: structured row has blank placeholders.
    db.upsert_case(case_id=1, run_id=run.id, method="", path="", state="done")

    # cases.db has the real route (populated by the agent before events arrive).
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-ooo"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"consume-test"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-ooo")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cases (id, method, url, type, status) VALUES (?, ?, ?, ?, ?)",
            (1, "GET", "/api/foo", "api", "done"),
        )
        conn.commit()

    # GET /cases must return method="GET" path="/api/foo", NOT blank.
    r_list = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                        headers={"Authorization": f"Bearer {token}"})
    assert r_list.status_code == 200
    cases = r_list.json()
    assert len(cases) == 1
    assert cases[0]["method"] == "GET", f"list: method should be GET, got {cases[0]['method']!r}"
    assert cases[0]["path"] == "/api/foo", f"list: path should be /api/foo, got {cases[0]['path']!r}"

    # GET /cases/1 must also return the real route.
    r_get = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/1",
                       headers={"Authorization": f"Bearer {token}"})
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["method"] == "GET", f"get: method should be GET, got {body['method']!r}"
    assert body["path"] == "/api/foo", f"get: path should be /api/foo, got {body['path']!r}"


def test_list_cases_per_field_merge_structured_values_win_when_populated(isolate_data_dir):
    """Bug 1 corollary: when structured has real values (normal order), they win.

    Verifies that the per-field merge does NOT regress the normal case where
    dispatch_start arrives first (structured has real method/path) and should
    take precedence over any stale cases.db values.
    """
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "ooo2_c4", isolate_data_dir)

    # Structured row has the real route.
    db.upsert_case(case_id=1, run_id=run.id, method="POST", path="/api/bar",
                   state="done", started_at=100, finished_at=200)

    # cases.db also has this case but with a different (stale) method; structured wins.
    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-ooo2"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"consume-test"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-ooo2")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cases (id, method, url, type, status) VALUES (?, ?, ?, ?, ?)",
            (1, "GET", "/api/bar", "api", "pending"),
        )
        conn.commit()

    r_list = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                        headers={"Authorization": f"Bearer {token}"})
    assert r_list.status_code == 200
    cases = r_list.json()
    assert len(cases) == 1
    # Structured POST wins over cases.db GET.
    assert cases[0]["method"] == "POST"
    # Structured state (done) wins over cases.db (queued from pending).
    assert cases[0]["state"] == "done"
    # Structured duration_ms is preserved.
    assert cases[0]["duration_ms"] == (200 - 100) * 1000


def test_agent_db_row_to_api_prefers_url_path_over_url(isolate_data_dir):
    """Bug 3: cases.db rows with url_path must return that in the path field.

    When the agent DB has both url (absolute) and url_path (route-only),
    the API must return url_path, not the absolute URL.
    """
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "urlpath_c4", isolate_data_dir)

    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-urlpath"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"consume-test"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-urlpath")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, url_path TEXT,
                type TEXT, status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cases (id, method, url, url_path, type, status) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "GET", "http://localhost:3000/api/foo", "/api/foo", "api", "done"),
        )
        conn.commit()

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 1
    # Must return url_path (/api/foo) not the absolute URL.
    assert cases[0]["path"] == "/api/foo", (
        f"Expected /api/foo but got {cases[0]['path']!r} — url_path not preferred over url"
    )

    # GET /cases/:id should also return url_path.
    r2 = client.get(f"/projects/{proj.id}/runs/{run.id}/cases/1",
                    headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["path"] == "/api/foo"


def test_agent_db_row_to_api_falls_back_to_url_when_url_path_missing(isolate_data_dir):
    """Bug 3 corollary: when url_path column is absent, fall back to url.

    Older cases.db schemas may not have url_path.  The API must still
    return the url value rather than an empty string.
    """
    import sqlite3

    client = TestClient(app)
    token, proj, run = _setup(client, "urlonly_c4", isolate_data_dir)

    eng_dir = isolate_data_dir / "workspace" / "engagements" / "eng-urlonly"
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"consume-test"}')
    (isolate_data_dir / "workspace" / "engagements" / ".active").write_text("engagements/eng-urlonly")

    cases_db_path = eng_dir / "cases.db"
    with sqlite3.connect(cases_db_path) as conn:
        conn.execute("""
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY, method TEXT, url TEXT, type TEXT, status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cases (id, method, url, type, status) VALUES (?, ?, ?, ?, ?)",
            (1, "GET", "http://localhost:3000/api/bar", "api", "done"),
        )
        conn.commit()

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/cases",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 1
    # No url_path column — fall back to the absolute url value.
    assert cases[0]["path"] == "http://localhost:3000/api/bar"


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
