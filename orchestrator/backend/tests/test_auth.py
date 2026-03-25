from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_create_user_login_and_me_requires_auth():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"username": "alice", "password": "secret-password"},
    )
    assert register_response.status_code == 201
    assert register_response.json() == {
        "id": 1,
        "username": "alice",
    }

    login_response = client.post(
        "/auth/login",
        json={"username": "alice", "password": "secret-password"},
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["token_type"] == "bearer"
    assert login_payload["access_token"]
    assert login_payload["user"] == {"id": 1, "username": "alice"}

    me_unauthenticated = client.get("/auth/me")
    assert me_unauthenticated.status_code == 401

    me_authenticated = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_payload['access_token']}"},
    )
    assert me_authenticated.status_code == 200
    assert me_authenticated.json() == {"id": 1, "username": "alice"}


def test_login_failure_and_duplicate_username():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"username": "bob", "password": "secret-password"},
    )
    assert register_response.status_code == 201

    duplicate_response = client.post(
        "/auth/register",
        json={"username": "bob", "password": "another-password"},
    )
    assert duplicate_response.status_code == 400

    bad_login_response = client.post(
        "/auth/login",
        json={"username": "bob", "password": "wrong-password"},
    )
    assert bad_login_response.status_code == 401


def test_invalid_or_unknown_bearer_token_is_rejected():
    client = TestClient(app)

    missing_token = client.get("/auth/me", headers={"Authorization": "Bearer"})
    assert missing_token.status_code == 401

    invalid_token = client.get("/auth/me", headers={"Authorization": "Bearer does-not-exist"})
    assert invalid_token.status_code == 401


def test_expired_session_token_is_rejected():
    client = TestClient(app)
    original_ttl = settings.session_ttl_hours
    object.__setattr__(settings, "session_ttl_hours", -1)
    try:
        register_response = client.post(
            "/auth/register",
            json={"username": "carol", "password": "secret-password"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/auth/login",
            json={"username": "carol", "password": "secret-password"},
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
    finally:
        object.__setattr__(settings, "session_ttl_hours", original_ttl)

    expired_me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert expired_me.status_code == 401
