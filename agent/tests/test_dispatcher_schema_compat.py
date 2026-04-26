from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = REPO_ROOT / "agent" / "scripts" / "dispatcher.sh"


def run_dispatcher(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DISPATCHER), str(db_path), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def table_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("PRAGMA table_info(cases)").fetchall()
    return {row[1] for row in rows}


def test_reset_stale_auto_migrates_consumed_at_column(tmp_path: Path) -> None:
    db_path = tmp_path / "cases.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, assigned_agent TEXT)"
        )
        connection.execute(
            "INSERT INTO cases(status, assigned_agent) VALUES ('processing', 'source-analyzer')"
        )
        connection.commit()

    result = run_dispatcher(db_path, "reset-stale", "10")

    assert result.returncode == 0, result.stderr
    assert "no such column consumed_at" not in result.stderr
    assert "consumed_at" in table_columns(db_path)


def test_fetch_auto_migrates_assigned_agent_column(tmp_path: Path) -> None:
    db_path = tmp_path / "cases.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases(type, status) VALUES ('api', 'pending')")
        connection.commit()

    result = run_dispatcher(db_path, "fetch", "api", "1", "vulnerability-analyst")

    assert result.returncode == 0, result.stderr
    assert "missing columns" not in result.stderr
    assert {"assigned_agent", "consumed_at"}.issubset(table_columns(db_path))
    assert '"assigned_agent":"vulnerability-analyst"' in result.stdout


def test_done_api_tested_is_terminal_done_status(tmp_path: Path) -> None:
    db_path = tmp_path / "cases.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE cases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL,
              status TEXT NOT NULL,
              stage TEXT NOT NULL DEFAULT 'ingested',
              assigned_agent TEXT,
              consumed_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO cases(type, status, stage, assigned_agent) VALUES ('api', 'processing', 'ingested', 'vulnerability-analyst')"
        )
        connection.commit()

    result = run_dispatcher(db_path, "done", "1", "--stage", "api_tested")

    assert result.returncode == 0, result.stderr
    assert "Marked done (stage=api_tested, terminal): 1" in result.stdout
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT status, stage FROM cases WHERE id=1").fetchone()
    assert row == ("done", "api_tested")
