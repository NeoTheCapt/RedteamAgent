from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings
from .models.event import Event
from .models.project import Project
from .models.run import Run
from .models.user import User


class UsernameAlreadyExistsError(Exception):
    pass


def database_path() -> Path:
    return settings.data_dir / "orchestrator.sqlite3"


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path()) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "expires_at" not in columns:
            connection.execute(
                "ALTER TABLE sessions ADD COLUMN expires_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                root_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, slug),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                engagement_root TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                phase TEXT NOT NULL,
                task_name TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    init_db()
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def create_user(username: str, password_hash: str, salt: str) -> User:
    with get_connection() as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO users (username, password_hash, salt)
                VALUES (?, ?, ?)
                """,
                (username, password_hash, salt),
            )
        except sqlite3.IntegrityError as exc:
            raise UsernameAlreadyExistsError(username) from exc
        row = connection.execute(
            "SELECT id, username, password_hash, salt, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        assert row is not None
        return User.from_row(row)


def get_user_by_username(username: str) -> User | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, salt, created_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
    return User.from_row(row) if row else None


def get_user_by_id(user_id: int) -> User | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, salt, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return User.from_row(row) if row else None


def create_session(user_id: int, token: str, expires_at: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (token, user_id, expires_at),
        )


def get_user_by_token(token: str, now_utc: str) -> User | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.password_hash, u.salt, u.created_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now_utc),
        ).fetchone()
    return User.from_row(row) if row else None


def create_project(user_id: int, name: str, slug: str, root_path: str) -> Project:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects (user_id, name, slug, root_path)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name, slug, root_path),
        )
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, created_at
            FROM projects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        assert row is not None
        return Project.from_row(row)


def get_project_by_user_and_slug(user_id: int, slug: str) -> Project | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, created_at
            FROM projects
            WHERE user_id = ? AND slug = ?
            """,
            (user_id, slug),
        ).fetchone()
    return Project.from_row(row) if row else None


def list_projects_for_user(user_id: int) -> list[Project]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, created_at
            FROM projects
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()
    return [Project.from_row(row) for row in rows]


def get_project_by_id(project_id: int) -> Project | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, created_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
    return Project.from_row(row) if row else None


def create_run(project_id: int, target: str, status: str, engagement_root: str) -> Run:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO runs (project_id, target, status, engagement_root)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, target, status, engagement_root),
        )
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at
            FROM runs
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        assert row is not None
        return Run.from_row(row)


def update_run_engagement_root(run_id: int, engagement_root: str) -> Run:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET engagement_root = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (engagement_root, run_id),
        )
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        return Run.from_row(row)


def list_runs_for_project(project_id: int) -> list[Run]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at
            FROM runs
            WHERE project_id = ?
            ORDER BY id ASC
            """,
            (project_id,),
        ).fetchall()
    return [Run.from_row(row) for row in rows]


def get_run_by_id(run_id: int) -> Run | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return Run.from_row(row) if row else None


def update_run_status(run_id: int, status: str) -> Run:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, run_id),
        )
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        return Run.from_row(row)


def create_event(
    run_id: int,
    event_type: str,
    phase: str,
    task_name: str,
    agent_name: str,
    summary: str,
) -> Event:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO events (run_id, event_type, phase, task_name, agent_name, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, phase, task_name, agent_name, summary),
        )
        row = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at
            FROM events
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        assert row is not None
        return Event.from_row(row)


def list_events_for_run(run_id: int) -> list[Event]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at
            FROM events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
    return [Event.from_row(row) for row in rows]


def get_latest_event_for_run(run_id: int, prefix: str) -> Event | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at
            FROM events
            WHERE run_id = ? AND event_type LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id, f"{prefix}%"),
        ).fetchone()
    return Event.from_row(row) if row else None
