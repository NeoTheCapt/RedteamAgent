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


def test_list_dispatches_returns_run_dispatches(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "a_c3", isolate_data_dir)
    db.upsert_dispatch(dispatch_id="B-1", run_id=run.id, phase="consume", round=1,
                       agent="vuln", slot="s0", task="x", state="running", started_at=1)

    r = client.get(
        f"/projects/{proj.id}/runs/{run.id}/dispatches",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "B-1"
    assert data[0]["agent"] == "vuln"
    assert data[0]["state"] == "running"


def test_list_dispatches_filters_by_phase(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "b_c3", isolate_data_dir)
    db.upsert_dispatch(dispatch_id="A", run_id=run.id, phase="recon", round=0,
                       agent="r", slot="s0", task="", state="done", started_at=1)
    db.upsert_dispatch(dispatch_id="B", run_id=run.id, phase="consume", round=1,
                       agent="v", slot="s0", task="", state="done", started_at=2)
    r = client.get(
        f"/projects/{proj.id}/runs/{run.id}/dispatches?phase=consume",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [d["id"] for d in r.json()] == ["B"]


def test_list_dispatches_rejects_other_users_run(isolate_data_dir):
    client = TestClient(app)
    alice_token = _register(client, "alice_c3_2")
    eve_token = _register(client, "eve_c3")
    alice_user = db.get_user_by_username("alice_c3_2")
    alice_proj = db.create_project(user_id=alice_user.id, name="ap", slug="ap",
                                   root_path=str(isolate_data_dir))
    alice_run = db.create_run(project_id=alice_proj.id, target="http://x",
                              status="running", engagement_root=str(isolate_data_dir))

    r = client.get(
        f"/projects/{alice_proj.id}/runs/{alice_run.id}/dispatches",
        headers={"Authorization": f"Bearer {eve_token}"},
    )
    assert r.status_code == 404


def test_list_dispatches_empty_for_new_run(isolate_data_dir):
    client = TestClient(app)
    token, proj, run = _setup(client, "empty_c3", isolate_data_dir)
    r = client.get(
        f"/projects/{proj.id}/runs/{run.id}/dispatches",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == []
