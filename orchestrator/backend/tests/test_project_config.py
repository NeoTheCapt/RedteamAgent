"""Tests for the three JSON config columns on the projects table.

Fixture conventions follow the existing test suite:
- `isolate_data_dir` is applied autouse=True in conftest.py (tmp_path backed).
- No explicit `db_conn` or `test_user` fixtures exist; tests call db directly.
"""
from __future__ import annotations

import json
import pytest

from app import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username: str = "testuser") -> db.User:
    return db.create_user(username, "ph", "salt")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_project_defaults_config_jsons_to_empty_object():
    user = _make_user("u_defaults")
    p = db.create_project(
        user_id=user.id, name="demo", slug="demo",
        root_path="/tmp/demo",
    )
    assert p.crawler_json == "{}"
    assert p.parallel_json == "{}"
    assert p.agents_json == "{}"


def test_create_project_accepts_config_jsons():
    user = _make_user("u_accepts")
    p = db.create_project(
        user_id=user.id, name="demo2", slug="demo2",
        root_path="/tmp/demo2",
        crawler_json='{"KATANA_CRAWL_DEPTH": 4}',
        parallel_json='{"REDTEAM_MAX_PARALLEL_BATCHES": 2}',
        agents_json='{"fuzzer": false}',
    )
    assert json.loads(p.crawler_json) == {"KATANA_CRAWL_DEPTH": 4}
    assert json.loads(p.parallel_json) == {"REDTEAM_MAX_PARALLEL_BATCHES": 2}
    assert json.loads(p.agents_json) == {"fuzzer": False}


def test_update_project_persists_new_config_field():
    user = _make_user("u_update1")
    p = db.create_project(user_id=user.id, name="u1", slug="u1", root_path="/tmp/u1")
    updated = db.update_project(p.id, crawler_json='{"KATANA_CRAWL_DEPTH": 16}')
    assert updated.crawler_json == '{"KATANA_CRAWL_DEPTH": 16}'
    # Unrelated fields untouched
    assert updated.parallel_json == "{}"
    assert updated.agents_json == "{}"
    assert updated.name == "u1"


def test_update_project_partial_leaves_other_columns():
    user = _make_user("u_update2")
    p = db.create_project(
        user_id=user.id, name="u2", slug="u2", root_path="/tmp/u2",
        crawler_json='{"KATANA_CRAWL_DEPTH": 3}',
        parallel_json='{"REDTEAM_MAX_PARALLEL_BATCHES": 5}',
    )
    # Patch only agents_json; confirm crawler + parallel unchanged
    updated = db.update_project(p.id, agents_json='{"fuzzer": true}')
    assert json.loads(updated.agents_json) == {"fuzzer": True}
    assert updated.crawler_json == '{"KATANA_CRAWL_DEPTH": 3}'
    assert updated.parallel_json == '{"REDTEAM_MAX_PARALLEL_BATCHES": 5}'


def test_update_project_multiple_fields_at_once():
    user = _make_user("u_update3")
    p = db.create_project(user_id=user.id, name="u3", slug="u3", root_path="/tmp/u3")
    updated = db.update_project(
        p.id,
        crawler_json='{"KATANA_CRAWL_DEPTH": 8}',
        parallel_json='{"REDTEAM_MAX_PARALLEL_BATCHES": 4}',
        agents_json='{"recon": true}',
    )
    assert json.loads(updated.crawler_json)["KATANA_CRAWL_DEPTH"] == 8
    assert json.loads(updated.parallel_json)["REDTEAM_MAX_PARALLEL_BATCHES"] == 4
    assert json.loads(updated.agents_json)["recon"] is True


def test_update_project_rejects_unknown_fields():
    user = _make_user("u_reject")
    p = db.create_project(user_id=user.id, name="ur", slug="ur", root_path="/tmp/ur")
    with pytest.raises(ValueError, match="Unknown project fields"):
        db.update_project(p.id, nonexistent_column="bad")


def test_update_project_requires_at_least_one_field():
    user = _make_user("u_empty")
    p = db.create_project(user_id=user.id, name="ue", slug="ue", root_path="/tmp/ue")
    with pytest.raises(ValueError):
        db.update_project(p.id)


def test_init_db_is_idempotent():
    # First call already happened via isolate_data_dir + get_connection.
    # Calling again must not raise.
    db.init_db()
    db.init_db()


def test_get_project_by_id_returns_config_fields():
    user = _make_user("u_get_id")
    p = db.create_project(
        user_id=user.id, name="g1", slug="g1", root_path="/tmp/g1",
        crawler_json='{"foo": 1}',
    )
    fetched = db.get_project_by_id(p.id)
    assert fetched is not None
    assert fetched.crawler_json == '{"foo": 1}'
    assert fetched.parallel_json == "{}"
    assert fetched.agents_json == "{}"


def test_get_project_by_user_and_slug_returns_config_fields():
    user = _make_user("u_slug")
    db.create_project(
        user_id=user.id, name="slug-test", slug="slug-test", root_path="/tmp/st",
        parallel_json='{"REDTEAM_MAX_PARALLEL_BATCHES": 7}',
    )
    fetched = db.get_project_by_user_and_slug(user.id, "slug-test")
    assert fetched is not None
    assert json.loads(fetched.parallel_json)["REDTEAM_MAX_PARALLEL_BATCHES"] == 7


def test_list_projects_for_user_returns_config_fields():
    user = _make_user("u_list")
    db.create_project(
        user_id=user.id, name="list1", slug="list1", root_path="/tmp/l1",
        agents_json='{"exploit_dev": false}',
    )
    db.create_project(
        user_id=user.id, name="list2", slug="list2", root_path="/tmp/l2",
        crawler_json='{"KATANA_CRAWL_DEPTH": 2}',
    )
    projects = db.list_projects_for_user(user.id)
    assert len(projects) == 2
    assert json.loads(projects[0].agents_json)["exploit_dev"] is False
    assert json.loads(projects[1].crawler_json)["KATANA_CRAWL_DEPTH"] == 2


def test_projects_table_has_three_new_columns():
    db.init_db()
    with db.get_connection() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    assert "crawler_json" in cols
    assert "parallel_json" in cols
    assert "agents_json" in cols
