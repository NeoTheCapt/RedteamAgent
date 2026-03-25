import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[3]
backend_root = repo_root / "orchestrator" / "backend"
sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def configure_temp_data_dir(tmp_path: Path) -> None:
    object.__setattr__(settings, "data_dir", tmp_path)


def test_create_user_login_and_me_requires_auth(tmp_path):
    configure_temp_data_dir(tmp_path)
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


def test_login_failure_and_duplicate_username(tmp_path):
    configure_temp_data_dir(tmp_path)
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
