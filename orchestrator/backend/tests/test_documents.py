from fastapi.testclient import TestClient
from app.main import app
from app import db


def _register(client, username="alice"):
    client.post("/auth/register", json={"username": username, "password": "secret-password"})
    return client.post("/auth/login",
                       json={"username": username, "password": "secret-password"}).json()["access_token"]


def _build_engagement(run_root, eng_id="eng-001"):
    """Create a realistic active engagement directory tree under run_root.

    Mirrors the launcher layout: run_root/workspace/engagements/<eng_id>/ with
    flat artifact files (findings.md, report.md, intel.md, surfaces.jsonl,
    scope.json, log.md) plus sensitive files that must be hidden and a nested
    runtime/ subfolder.

    Returns the active engagement directory path.
    """
    eng_dir = run_root / "workspace" / "engagements" / eng_id
    eng_dir.mkdir(parents=True)
    (eng_dir / "scope.json").write_text('{"current_phase":"report"}')
    (eng_dir / "log.md").write_text("# log")
    (eng_dir / "findings.md").write_text("# findings body")
    (eng_dir / "report.md").write_text("# report body")
    (eng_dir / "intel.md").write_text("# intel body")
    (eng_dir / "surfaces.jsonl").write_text('{"route":"/x"}\n')
    (eng_dir / "runtime").mkdir()
    (eng_dir / "runtime" / "process.log").write_text("proc output")
    # Sensitive files MUST be omitted from listings
    (eng_dir / "intel-secrets.json").write_text('{"key":"secret"}')
    (eng_dir / "auth.json").write_text('{"token":"x"}')
    # Mark it active so _active_engagement_root resolves deterministically
    (run_root / "workspace" / "engagements" / ".active").write_text(f"engagements/{eng_id}")
    return eng_dir


def test_list_documents_tree(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d1")
    user = db.get_user_by_username("d1")

    run_root = isolate_data_dir / "run_d1"
    run_root.mkdir()
    _build_engagement(run_root)

    proj = db.create_project(user_id=user.id, name="d1", slug="d1",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    tree = r.json()

    # All five buckets exist
    for bucket in ("findings", "reports", "intel", "surface", "other"):
        assert bucket in tree

    # findings.md → findings bucket
    findings = {e["name"] for e in tree["findings"]}
    assert findings == {"findings.md"}

    # report.md → reports bucket
    reports = {e["name"] for e in tree["reports"]}
    assert reports == {"report.md"}

    # intel.md → intel bucket (NOT intel-secrets.json)
    intel = {e["name"] for e in tree["intel"]}
    assert intel == {"intel.md"}

    # surfaces.jsonl → surface bucket
    surface = {e["name"] for e in tree["surface"]}
    assert surface == {"surfaces.jsonl"}

    # scope.json / log.md / runtime/process.log → other
    other_paths = {e["path"] for e in tree["other"]}
    assert "scope.json" in other_paths
    assert "log.md" in other_paths
    assert "runtime/process.log" in other_paths

    # Sensitive files MUST NOT appear anywhere
    all_names = {
        e["name"] for entries in tree.values() for e in entries
    }
    assert "auth.json" not in all_names
    assert "intel-secrets.json" not in all_names

    # Entry shape
    for entry in tree["findings"]:
        assert "name" in entry
        assert "path" in entry
        assert "size" in entry
        assert "mtime" in entry
        assert entry["size"] > 0


def test_get_document_content(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d2")
    user = db.get_user_by_username("d2")

    run_root = isolate_data_dir / "run_d2"
    run_root.mkdir()
    _build_engagement(run_root)

    proj = db.create_project(user_id=user.id, name="d2", slug="d2",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/findings.md",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "findings.md"
    assert body["content"] == "# findings body"


def test_get_document_reads_nested_path(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d2b")
    user = db.get_user_by_username("d2b")

    run_root = isolate_data_dir / "run_d2b"
    run_root.mkdir()
    _build_engagement(run_root)

    proj = db.create_project(user_id=user.id, name="d2b", slug="d2b",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/runtime/process.log",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["content"] == "proc output"


def test_get_document_rejects_sensitive(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d_sens")
    user = db.get_user_by_username("d_sens")

    run_root = isolate_data_dir / "run_sens"
    run_root.mkdir()
    _build_engagement(run_root)

    proj = db.create_project(user_id=user.id, name="d_sens", slug="d_sens",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    # Sensitive files are not listed AND not readable via the documents endpoint
    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/auth.json",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404

    r2 = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/intel-secrets.json",
                    headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 404


def test_get_document_404_for_missing(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d3")
    user = db.get_user_by_username("d3")

    run_root = isolate_data_dir / "run_d3"
    run_root.mkdir()
    _build_engagement(run_root)

    proj = db.create_project(user_id=user.id, name="d3", slug="d3",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/nope.md",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_get_document_rejects_path_escape(isolate_data_dir):
    """Raw ASGI injection — verify handler rejects path escape before httpx normalizes."""
    from starlette.testclient import TestClient as ST
    from app.main import app as asgi_app

    client = ST(asgi_app)
    token = _register(client, "d4")
    user = db.get_user_by_username("d4")

    run_root = isolate_data_dir / "run_d4"
    run_root.mkdir()
    _build_engagement(run_root)
    (isolate_data_dir / "secret.txt").write_text("super-secret")

    proj = db.create_project(user_id=user.id, name="d4", slug="d4",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    # Build a raw ASGI call with literal ../ in the path (httpx would normalize it).
    import asyncio
    async def call():
        raw_path = (
            f"/projects/{proj.id}/runs/{run.id}/documents/../../../../secret.txt"
        ).encode()
        scope = {
            "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": raw_path.decode(),
            "raw_path": raw_path,
            "root_path": "", "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"authorization", f"Bearer {token}".encode()),
            ],
            "client": ("testclient", 0), "server": ("testserver", 80),
        }
        sent = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(msg):
            sent.append(msg)
        await asgi_app(scope, receive, send)
        return sent
    sent = asyncio.new_event_loop().run_until_complete(call())
    status_msg = next(m for m in sent if m["type"] == "http.response.start")
    assert status_msg["status"] in (400, 404)


def test_documents_rejects_other_users_run(isolate_data_dir):
    client = TestClient(app)
    _register(client, "alice_d")
    eve_token = _register(client, "eve_d")
    alice_user = db.get_user_by_username("alice_d")

    run_root = isolate_data_dir / "run_alice"
    run_root.mkdir()
    _build_engagement(run_root)

    alice_proj = db.create_project(user_id=alice_user.id, name="ap", slug="ap_d",
                                   root_path=str(isolate_data_dir))
    alice_run = db.create_run(project_id=alice_proj.id, target="http://x",
                              status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{alice_proj.id}/runs/{alice_run.id}/documents",
                   headers={"Authorization": f"Bearer {eve_token}"})
    assert r.status_code == 404


def test_documents_missing_engagement_returns_empty(isolate_data_dir):
    """If the workspace has no engagement dir yet, tree should be empty buckets (not crash)."""
    client = TestClient(app)
    token = _register(client, "d_empty")
    user = db.get_user_by_username("d_empty")

    run_root = isolate_data_dir / "run_empty"
    run_root.mkdir()  # no workspace/engagements/ subdir at all

    proj = db.create_project(user_id=user.id, name="e", slug="e",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(run_root))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    tree = r.json()
    for bucket in ("findings", "reports", "intel", "surface", "other"):
        assert tree[bucket] == []
