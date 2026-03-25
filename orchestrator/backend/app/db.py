from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings
from .models.user import User


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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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
        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, salt)
            VALUES (?, ?, ?)
            """,
            (username, password_hash, salt),
        )
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


def create_session(user_id: int, token: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (token, user_id)
            VALUES (?, ?)
            """,
            (token, user_id),
        )


def get_user_by_token(token: str) -> User | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.password_hash, u.salt, u.created_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    return User.from_row(row) if row else None
