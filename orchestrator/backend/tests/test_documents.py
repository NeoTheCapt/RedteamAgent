from fastapi.testclient import TestClient
from app.main import app
from app import db


def _register(client, username="alice"):
    client.post("/auth/register", json={"username": username, "password": "secret-password"})
    return client.post("/auth/login",
                       json={"username": username, "password": "secret-password"}).json()["access_token"]


def test_list_documents_tree(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d1")
    user = db.get_user_by_username("d1")

    eng = isolate_data_dir / "eng_d1"
    eng.mkdir()
    (eng / "findings").mkdir()
    (eng / "findings" / "F1.md").write_text("# f1")
    (eng / "intel").mkdir()
    (eng / "intel" / "recon.md").write_text("# recon")
    (eng / "reports").mkdir()  # empty folder
    # No artifacts, no surface

    proj = db.create_project(user_id=user.id, name="d1_proj", slug="d1",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    tree = r.json()

    assert "findings" in tree
    assert "intel" in tree
    assert "surface" in tree
    assert "artifacts" in tree
    assert "reports" in tree

    findings = tree["findings"]
    assert len(findings) == 1
    assert findings[0]["name"] == "F1.md"
    assert findings[0]["path"] == "findings/F1.md"
    assert findings[0]["size"] > 0
    assert isinstance(findings[0]["mtime"], int)

    assert len(tree["intel"]) == 1
    assert tree["intel"][0]["name"] == "recon.md"

    assert tree["reports"] == []
    assert tree["surface"] == []
    assert tree["artifacts"] == []


def test_list_documents_recurses_subfolders(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d_rec")
    user = db.get_user_by_username("d_rec")

    eng = isolate_data_dir / "eng_rec"
    (eng / "artifacts" / "screenshots").mkdir(parents=True)
    (eng / "artifacts" / "screenshots" / "login.png").write_bytes(b"fakepng")
    (eng / "artifacts" / "payloads.txt").write_text("xss")

    proj = db.create_project(user_id=user.id, name="rec", slug="rec",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents",
                   headers={"Authorization": f"Bearer {token}"})
    paths = {e["path"] for e in r.json()["artifacts"]}
    assert "artifacts/screenshots/login.png" in paths
    assert "artifacts/payloads.txt" in paths


def test_get_document_content(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d2")
    user = db.get_user_by_username("d2")
    eng = isolate_data_dir / "eng_d2"
    (eng / "findings").mkdir(parents=True)
    (eng / "findings" / "F1.md").write_text("# finding body")

    proj = db.create_project(user_id=user.id, name="d2_proj", slug="d2",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/findings/F1.md",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "findings/F1.md"
    assert body["content"] == "# finding body"


def test_get_document_404_for_missing(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d3")
    user = db.get_user_by_username("d3")
    eng = isolate_data_dir / "eng_d3"; eng.mkdir()
    proj = db.create_project(user_id=user.id, name="d3_proj", slug="d3",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/findings/nope.md",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_get_document_rejects_path_escape(isolate_data_dir):
    # httpx normalizes "../" in URLs before sending, so we craft a raw ASGI scope
    # to verify the handler itself rejects path escape attempts.
    import asyncio

    client = TestClient(app)
    token = _register(client, "d4")
    user = db.get_user_by_username("d4")
    eng = isolate_data_dir / "eng_d4"; eng.mkdir()
    (isolate_data_dir / "secret.txt").write_text("super-secret")

    proj = db.create_project(user_id=user.id, name="d4_proj", slug="d4",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    raw_path = f"/projects/{proj.id}/runs/{run.id}/documents/../secret.txt".encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": raw_path.decode(),
        "raw_path": raw_path,
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"authorization", f"Bearer {token}".encode()),
        ],
        "client": ("testclient", 0), "server": ("testserver", 80), "root_path": "",
    }
    captured: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        captured.append(msg)

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    start = next(m for m in captured if m["type"] == "http.response.start")
    assert start["status"] in (400, 404)


def test_get_document_413_for_oversized(isolate_data_dir):
    client = TestClient(app)
    token = _register(client, "d5")
    user = db.get_user_by_username("d5")
    eng = isolate_data_dir / "eng_d5"
    (eng / "artifacts").mkdir(parents=True)
    # 1.5 MB file
    (eng / "artifacts" / "big.bin").write_bytes(b"x" * (1024 * 1024 + 100_000))

    proj = db.create_project(user_id=user.id, name="d5_proj", slug="d5",
                             root_path=str(isolate_data_dir))
    run = db.create_run(project_id=proj.id, target="http://x",
                        status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{proj.id}/runs/{run.id}/documents/artifacts/big.bin",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 413


def test_documents_rejects_other_users_run(isolate_data_dir):
    client = TestClient(app)
    _register(client, "alice_c6")
    eve_token = _register(client, "eve_c6")
    alice_user = db.get_user_by_username("alice_c6")
    eng = isolate_data_dir / "eng_alice"; eng.mkdir()
    alice_proj = db.create_project(user_id=alice_user.id, name="ap", slug="ap_c6",
                                   root_path=str(isolate_data_dir))
    alice_run = db.create_run(project_id=alice_proj.id, target="http://x",
                              status="running", engagement_root=str(eng))

    r = client.get(f"/projects/{alice_proj.id}/runs/{alice_run.id}/documents",
                   headers={"Authorization": f"Bearer {eve_token}"})
    assert r.status_code == 404
