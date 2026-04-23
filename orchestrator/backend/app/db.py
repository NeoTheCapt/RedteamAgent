from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings
from .models.case import Case
from .models.dispatch import Dispatch
from .models.event import Event
from .models.project import Project
from .models.run import Run
from .models.user import User


class UsernameAlreadyExistsError(Exception):
    pass


class RunNotFoundError(Exception):
    pass


_INIT_LOCK = threading.Lock()
_INITIALIZED_DB_PATH: Path | None = None
# Auth-gated UI routes can fan out many concurrent requests; brief filesystem or
# sqlite open hiccups on the main orchestrator DB should not blank the whole UI.
# Keep retrying long enough to ride out transient "unable to open database file"
# failures observed in live summary/cases/ws-ticket polling.
_DB_OPEN_RETRY_ATTEMPTS = 20
_DB_OPEN_RETRY_DELAY_SECONDS = 0.1


def database_path() -> Path:
    return (settings.data_dir / "orchestrator.sqlite3").resolve()


def _is_retryable_open_error(exc: sqlite3.OperationalError) -> bool:
    return "unable to open database file" in str(exc).lower()


def _connect_database(*, timeout: float = 5.0) -> sqlite3.Connection:
    db_path = database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: sqlite3.OperationalError | None = None
    for attempt in range(_DB_OPEN_RETRY_ATTEMPTS):
        try:
            connection = sqlite3.connect(db_path, timeout=timeout)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite3.OperationalError as exc:
            if not _is_retryable_open_error(exc) or attempt == _DB_OPEN_RETRY_ATTEMPTS - 1:
                raise
            last_error = exc
            time.sleep(_DB_OPEN_RETRY_DELAY_SECONDS)

    assert last_error is not None
    raise last_error


def init_db() -> None:
    global _INITIALIZED_DB_PATH
    current_db_path = database_path()
    if _INITIALIZED_DB_PATH == current_db_path:
        return

    with _INIT_LOCK:
        current_db_path = database_path()
        if _INITIALIZED_DB_PATH == current_db_path:
            return
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with _connect_database() as connection:
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
                provider_id TEXT NOT NULL DEFAULT '',
                model_id TEXT NOT NULL DEFAULT '',
                small_model_id TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                auth_json TEXT NOT NULL DEFAULT '',
                env_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, slug),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        project_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "provider_id" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN provider_id TEXT NOT NULL DEFAULT ''")
        if "model_id" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN model_id TEXT NOT NULL DEFAULT ''")
        if "small_model_id" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN small_model_id TEXT NOT NULL DEFAULT ''")
        if "api_key" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN api_key TEXT NOT NULL DEFAULT ''")
        if "base_url" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN base_url TEXT NOT NULL DEFAULT ''")
        if "auth_json" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN auth_json TEXT NOT NULL DEFAULT ''")
        if "env_json" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN env_json TEXT NOT NULL DEFAULT ''")
        for col in ("crawler_json", "parallel_json", "agents_json"):
            try:
                connection.execute(
                    f"ALTER TABLE projects ADD COLUMN {col} TEXT NOT NULL DEFAULT '{{}}'"
                )
            except sqlite3.OperationalError:
                pass  # already exists
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
        # Migration from branch-early schema: if dispatches had singleton PK on `id`,
        # rebuild with composite PK (run_id, id). Safe because this table only gained
        # rows after this branch landed and dev DBs carry no production data.
        # Order matters: drop `cases` BEFORE `dispatches` because cases has an FK
        # into dispatches — dropping dispatches first would leave cases pointing at
        # a phantom.
        cases_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='cases'"
        ).fetchone()
        if cases_row is not None and "FOREIGN KEY(run_id, dispatch_id)" not in (cases_row[0] or ""):
            connection.execute("DROP TABLE IF EXISTS cases")
        dispatches_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='dispatches'"
        ).fetchone()
        if dispatches_row is not None and "PRIMARY KEY (run_id" not in (dispatches_row[0] or ""):
            connection.execute("DROP TABLE IF EXISTS dispatches")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatches (
                id TEXT NOT NULL,
                run_id INTEGER NOT NULL,
                phase TEXT NOT NULL,
                round INTEGER NOT NULL DEFAULT 0,
                agent TEXT NOT NULL,
                slot TEXT NOT NULL,
                task TEXT,
                state TEXT NOT NULL,
                started_at INTEGER,
                finished_at INTEGER,
                error TEXT,
                PRIMARY KEY (run_id, id),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_dispatches_run ON dispatches(run_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                category TEXT,
                dispatch_id TEXT,
                state TEXT NOT NULL,
                result TEXT,
                finding_id TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                PRIMARY KEY (run_id, case_id),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
                FOREIGN KEY(run_id, dispatch_id) REFERENCES dispatches(run_id, id) ON DELETE SET NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_run_state ON cases(run_id, state)"
        )
        for column_sql in [
            "ALTER TABLE events ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'",
            "ALTER TABLE events ADD COLUMN level TEXT NOT NULL DEFAULT 'info'",
            "ALTER TABLE events ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'",
        ]:
            try:
                connection.execute(column_sql)
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events(run_id, kind)"
        )
        for column_sql in [
            "ALTER TABLE runs ADD COLUMN current_phase TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE runs ADD COLUMN current_round INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE runs ADD COLUMN parallel_config TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE runs ADD COLUMN benchmark_json TEXT NOT NULL DEFAULT '{}'",
        ]:
            try:
                connection.execute(column_sql)
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        connection.commit()
        _INITIALIZED_DB_PATH = current_db_path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    init_db()
    connection = _connect_database()
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


def create_project(
    user_id: int,
    name: str,
    slug: str,
    root_path: str,
    *,
    provider_id: str = "",
    model_id: str = "",
    small_model_id: str = "",
    api_key: str = "",
    base_url: str = "",
    auth_json: str = "",
    env_json: str = "",
    crawler_json: str = "{}",
    parallel_json: str = "{}",
    agents_json: str = "{}",
) -> Project:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects (user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json),
        )
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
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
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
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
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
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
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
    return Project.from_row(row) if row else None


def update_project_config(
    project_id: int,
    *,
    provider_id: str,
    model_id: str,
    small_model_id: str,
    api_key: str,
    base_url: str,
    auth_json: str,
    env_json: str,
) -> Project:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE projects
            SET provider_id = ?, model_id = ?, small_model_id = ?, api_key = ?, base_url = ?, auth_json = ?, env_json = ?
            WHERE id = ?
            """,
            (provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, project_id),
        )
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
    assert row is not None
    return Project.from_row(row)


_UPDATABLE_PROJECT_FIELDS = frozenset({
    "name", "slug", "provider_id", "model_id", "small_model_id",
    "api_key", "base_url", "auth_json", "env_json",
    "crawler_json", "parallel_json", "agents_json",
})


def update_project(project_id: int, **fields: str) -> Project:
    """Update any subset of allowed project fields and return the refreshed Project.

    Only columns listed in _UPDATABLE_PROJECT_FIELDS are accepted; unknown keys
    raise ValueError to prevent SQL injection via dynamic column names.
    """
    if not fields:
        raise ValueError("update_project requires at least one field")
    unknown = set(fields) - _UPDATABLE_PROJECT_FIELDS
    if unknown:
        raise ValueError(f"Unknown project fields: {unknown}")
    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [project_id]
    with get_connection() as connection:
        connection.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?",
            values,
        )
        row = connection.execute(
            """
            SELECT id, user_id, name, slug, root_path, provider_id, model_id, small_model_id, api_key, base_url, auth_json, env_json, crawler_json, parallel_json, agents_json, created_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
    assert row is not None
    return Project.from_row(row)


def delete_project(project_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM projects
            WHERE id = ?
            """,
            (project_id,),
        )


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
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
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
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
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
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE project_id = ?
            ORDER BY id ASC
            """,
            (project_id,),
        ).fetchall()
    return [Run.from_row(row) for row in rows]


def list_runs_by_status(status_value: str) -> list[Run]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE status = ?
            ORDER BY id ASC
            """,
            (status_value,),
        ).fetchall()
    return [Run.from_row(row) for row in rows]


def get_run_by_id(run_id: int) -> Run | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return Run.from_row(row) if row else None


def delete_run(run_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM runs
            WHERE id = ?
            """,
            (run_id,),
        )


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
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise RunNotFoundError(f"Run {run_id} not found")
        run = Run.from_row(row)

    _write_run_metadata(run)
    return run


def set_run_updated_at(run_id: int, updated_at: str) -> Run:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET updated_at = ?
            WHERE id = ?
            """,
            (updated_at, run_id),
        )
        row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise RunNotFoundError(f"Run {run_id} not found")
        run = Run.from_row(row)

    _write_run_metadata(run)
    return run


def _write_run_metadata(run: Run) -> None:
    metadata_path = Path(run.engagement_root) / "run.json"
    if not metadata_path.exists():
        return
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    payload["id"] = run.id
    payload["run_id"] = run.id
    payload["project_id"] = run.project_id
    payload["target"] = run.target
    payload["status"] = run.status
    payload["engagement_root"] = run.engagement_root
    payload["created_at"] = run.created_at
    payload["updated_at"] = run.updated_at
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_event(
    run_id: int,
    event_type: str,
    phase: str,
    task_name: str,
    agent_name: str,
    summary: str,
    *,
    kind: str = "legacy",
    level: str = "info",
    payload_json: str = "{}",
) -> Event:
    with get_connection() as connection:
        if event_type != "run.heartbeat":
            connection.execute(
                """
                UPDATE runs
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (run_id,),
            )
        cursor = connection.execute(
            """
            INSERT INTO events
                (run_id, event_type, phase, task_name, agent_name, summary,
                 kind, level, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, phase, task_name, agent_name, summary,
             kind, level, payload_json),
        )
        row = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at,
                   kind, level, payload_json
            FROM events
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        run_row = connection.execute(
            """
            SELECT id, project_id, target, status, engagement_root, created_at, updated_at,
                   current_phase, current_round, parallel_config, benchmark_json
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        assert run_row is not None
        _write_run_metadata(Run.from_row(run_row))
        return Event.from_row(row)


def list_events_for_run(run_id: int) -> list[Event]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at,
                   kind, level, payload_json
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


def get_latest_non_heartbeat_event_for_run(run_id: int, prefix: str = "") -> Event | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, run_id, event_type, phase, task_name, agent_name, summary, created_at
            FROM events
            WHERE run_id = ?
              AND event_type != 'run.heartbeat'
              AND event_type LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id, f"{prefix}%"),
        ).fetchone()
    return Event.from_row(row) if row else None


def upsert_dispatch(
    *,
    dispatch_id: str,
    run_id: int,
    phase: str,
    round: int,
    agent: str,
    slot: str,
    task: str | None,
    state: str,
    started_at: int | None = None,
    finished_at: int | None = None,
    error: str | None = None,
) -> Dispatch:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO dispatches (id, run_id, phase, round, agent, slot, task,
                                    state, started_at, finished_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, id) DO UPDATE SET
                state=excluded.state,
                -- Preserve metadata from the first non-empty write (supports
                -- out-of-order delivery where dispatch_done arrives before
                -- dispatch_start with an empty-string placeholder row).
                phase=CASE WHEN excluded.phase != '' THEN excluded.phase ELSE dispatches.phase END,
                round=CASE WHEN excluded.round != 0 THEN excluded.round ELSE dispatches.round END,
                agent=CASE WHEN excluded.agent != '' THEN excluded.agent ELSE dispatches.agent END,
                slot=CASE WHEN excluded.slot != '' THEN excluded.slot ELSE dispatches.slot END,
                task=COALESCE(excluded.task, dispatches.task),
                started_at=COALESCE(excluded.started_at, dispatches.started_at),
                finished_at=COALESCE(excluded.finished_at, dispatches.finished_at),
                error=COALESCE(excluded.error, dispatches.error)
            """,
            (dispatch_id, run_id, phase, round, agent, slot, task,
             state, started_at, finished_at, error),
        )
        conn.commit()
    return get_dispatch(run_id, dispatch_id)


def get_dispatch(run_id: int, dispatch_id: str) -> Dispatch | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dispatches WHERE run_id = ? AND id = ?",
            (run_id, dispatch_id),
        ).fetchone()
    return Dispatch.from_row(row) if row else None


def list_dispatches(run_id: int, phase: str | None = None) -> list[Dispatch]:
    sql = "SELECT * FROM dispatches WHERE run_id = ?"
    args: list = [run_id]
    if phase:
        sql += " AND phase = ?"
        args.append(phase)
    sql += " ORDER BY started_at IS NULL, started_at, id"
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [Dispatch.from_row(r) for r in rows]


def upsert_case(
    *,
    case_id: int,
    run_id: int,
    method: str,
    path: str,
    category: str | None = None,
    dispatch_id: str | None = None,
    state: str,
    result: str | None = None,
    finding_id: str | None = None,
    started_at: int | None = None,
    finished_at: int | None = None,
) -> Case:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO cases (case_id, run_id, method, path, category, dispatch_id,
                               state, result, finding_id, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, case_id) DO UPDATE SET
                method=excluded.method,
                path=excluded.path,
                category=COALESCE(excluded.category, cases.category),
                dispatch_id=COALESCE(excluded.dispatch_id, cases.dispatch_id),
                state=excluded.state,
                result=COALESCE(excluded.result, cases.result),
                finding_id=COALESCE(excluded.finding_id, cases.finding_id),
                started_at=COALESCE(excluded.started_at, cases.started_at),
                finished_at=COALESCE(excluded.finished_at, cases.finished_at)
            """,
            (case_id, run_id, method, path, category, dispatch_id,
             state, result, finding_id, started_at, finished_at),
        )
        conn.commit()
    return get_case(run_id, case_id)


def get_case(run_id: int, case_id: int) -> Case | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE run_id = ? AND case_id = ?",
            (run_id, case_id),
        ).fetchone()
    return Case.from_row(row) if row else None


def list_cases(
    run_id: int, *,
    state: str | None = None,
    method: str | None = None,
    category: str | None = None,
) -> list[Case]:
    sql = "SELECT * FROM cases WHERE run_id = ?"
    args: list = [run_id]
    for col, val in (("state", state), ("method", method), ("category", category)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    sql += " ORDER BY case_id"
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [Case.from_row(r) for r in rows]
