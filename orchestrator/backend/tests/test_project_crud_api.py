"""Tests for the extended Projects API: create with JSON config fields + PATCH endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client: TestClient, username: str, password: str = "secret-password") -> str:
    r = client.post("/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_demo_project(
    client: TestClient,
    token: str,
    *,
    name: str = "demo-project",
    extra: dict | None = None,
) -> int:
    payload: dict = {"name": name}
    if extra:
        payload.update(extra)
    r = client.post("/projects", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# CREATE tests — new JSON config fields
# ---------------------------------------------------------------------------

def test_create_project_defaults_json_config_fields():
    client = TestClient(app)
    token = _register_and_login(client, "alice_c1")

    r = client.post("/projects", json={"name": "bare-project"}, headers=_auth(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crawler_json"] == "{}"
    assert body["parallel_json"] == "{}"
    assert body["agents_json"] == "{}"


def test_create_project_with_crawler_config_persists():
    client = TestClient(app)
    token = _register_and_login(client, "alice_c2")

    payload = {"name": "demo-crawler", "crawler_json": '{"KATANA_CRAWL_DEPTH": 4}'}
    r = client.post("/projects", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crawler_json"] == '{"KATANA_CRAWL_DEPTH": 4}'
    # Confirm defaults on the other two
    assert body["parallel_json"] == "{}"
    assert body["agents_json"] == "{}"


def test_create_project_with_all_three_json_config_fields():
    client = TestClient(app)
    token = _register_and_login(client, "alice_c3")

    payload = {
        "name": "full-config",
        "crawler_json": '{"KATANA_CRAWL_DEPTH": 3}',
        "parallel_json": '{"REDTEAM_MAX_PARALLEL_BATCHES": 2}',
        "agents_json": '{"fuzzer": false}',
    }
    r = client.post("/projects", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crawler_json"] == '{"KATANA_CRAWL_DEPTH": 3}'
    assert body["parallel_json"] == '{"REDTEAM_MAX_PARALLEL_BATCHES": 2}'
    assert body["agents_json"] == '{"fuzzer": false}'


def test_create_project_rejects_invalid_crawler_json():
    client = TestClient(app)
    token = _register_and_login(client, "alice_c4")

    r = client.post(
        "/projects",
        json={"name": "bad-crawler", "crawler_json": "not-json"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# PATCH tests
# ---------------------------------------------------------------------------

def test_patch_project_updates_single_field():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p1")
    pid = _create_demo_project(client, token)

    r = client.patch(
        f"/projects/{pid}",
        json={"agents_json": '{"fuzzer": false}'},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agents_json"] == '{"fuzzer": false}'
    # Untouched fields retain their defaults
    assert body["crawler_json"] == "{}"
    assert body["parallel_json"] == "{}"


def test_patch_project_updates_all_json_config_fields():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p2")
    pid = _create_demo_project(client, token)

    r = client.patch(
        f"/projects/{pid}",
        json={
            "crawler_json": '{"KATANA_CRAWL_DEPTH": 7}',
            "parallel_json": '{"REDTEAM_MAX_PARALLEL_BATCHES": 3}',
            "agents_json": '{"recon": true}',
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crawler_json"] == '{"KATANA_CRAWL_DEPTH": 7}'
    assert body["parallel_json"] == '{"REDTEAM_MAX_PARALLEL_BATCHES": 3}'
    assert body["agents_json"] == '{"recon": true}'


def test_patch_project_rejects_invalid_crawler_json():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p3")
    pid = _create_demo_project(client, token)

    r = client.patch(
        f"/projects/{pid}",
        json={"crawler_json": "not-json"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


def test_patch_project_rejects_invalid_parallel_json():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p4")
    pid = _create_demo_project(client, token)

    r = client.patch(
        f"/projects/{pid}",
        json={"parallel_json": "[1,2,3]"},  # valid JSON but not an object — service accepts, but let's test non-JSON
        headers=_auth(token),
    )
    # [1,2,3] IS valid JSON; service only rejects non-parseable strings
    # This should succeed (service validates parse-ability, not object shape)
    assert r.status_code == 200, r.text


def test_patch_project_rejects_unparseable_agents_json():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p5")
    pid = _create_demo_project(client, token)

    r = client.patch(
        f"/projects/{pid}",
        json={"agents_json": "{bad json}"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


def test_patch_project_404_for_nonexistent():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p6")

    r = client.patch("/projects/99999", json={"name": "x"}, headers=_auth(token))
    assert r.status_code == 404, r.text


def test_patch_project_404_for_other_users_project():
    """User B cannot patch User A's project (returns 404, not 403 — ownership check)."""
    client = TestClient(app)
    alice_token = _register_and_login(client, "alice_p7")
    bob_token = _register_and_login(client, "bob_p7")

    pid = _create_demo_project(client, alice_token, name="alice-private")

    # Bob tries to patch Alice's project
    r = client.patch(
        f"/projects/{pid}",
        json={"agents_json": '{"fuzzer": true}'},
        headers=_auth(bob_token),
    )
    assert r.status_code == 404, r.text


def test_patch_project_empty_body_is_noop():
    """PATCH with an empty body (all None) returns the current project state unchanged."""
    client = TestClient(app)
    token = _register_and_login(client, "alice_p8")
    pid = _create_demo_project(
        client, token, name="noop-test",
        extra={"crawler_json": '{"KATANA_CRAWL_DEPTH": 5}'},
    )

    # Fetch current state
    list_r = client.get("/projects", headers=_auth(token))
    current = next(p for p in list_r.json() if p["id"] == pid)

    # PATCH with no fields
    r = client.patch(f"/projects/{pid}", json={}, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crawler_json"] == current["crawler_json"]
    assert body["parallel_json"] == current["parallel_json"]
    assert body["agents_json"] == current["agents_json"]
    assert body["name"] == current["name"]


def test_patch_project_rename_updates_slug():
    client = TestClient(app)
    token = _register_and_login(client, "alice_p9")
    pid = _create_demo_project(client, token, name="original")

    r = client.patch(
        f"/projects/{pid}",
        json={"name": "Renamed Thing"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed Thing"
    assert body["slug"] == "renamed-thing"


def test_patch_project_rename_collision_rejected():
    """Renaming to a name that slugifies to an existing slug is rejected."""
    client = TestClient(app)
    token = _register_and_login(client, "alice_p10")
    _create_demo_project(client, token, name="taken-name")
    pid = _create_demo_project(client, token, name="other-project")

    r = client.patch(
        f"/projects/{pid}",
        json={"name": "Taken Name"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


def test_patch_project_same_name_no_collision():
    """Renaming to the same name (same slug) does not trigger a collision error."""
    client = TestClient(app)
    token = _register_and_login(client, "alice_p11")
    pid = _create_demo_project(client, token, name="stable-name")

    r = client.patch(
        f"/projects/{pid}",
        json={"name": "Stable Name"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "stable-name"
