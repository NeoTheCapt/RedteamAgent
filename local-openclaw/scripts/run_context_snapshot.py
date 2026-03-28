#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("ORCH_BASE_URL", "http://127.0.0.1:18000").rstrip("/")
TOKEN = os.environ.get("ORCH_TOKEN", "")
PROJECT_ID = os.environ.get("PROJECT_ID", "")


def api_get(path: str, default: Any) -> Any:
    request = Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return default


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _tail(path: Path, lines: int = 10) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return "".join(handle.readlines()[-lines:]).rstrip("\n")


def _artifact_snapshot(engagement_dir: Path) -> dict[str, Any]:
    artifact = {
        "cases": {
            "total_cases": 0,
            "completed_cases": 0,
            "pending_cases": 0,
            "processing_cases": 0,
            "error_cases": 0,
            "case_types": [],
            "processing_agents": [],
            "source_counts": [],
        },
        "observed_paths": [],
        "files": {
            "engagement_dir": str(engagement_dir),
            "cases_db_exists": False,
            "surfaces_lines": 0,
            "katana_output_lines": 0,
            "katana_error_tail": "",
        },
        "integrity": {
            "summary_api_suspicious": False,
            "observed_api_suspicious": False,
            "fallback_applied": False,
            "reasons": [],
        },
    }

    if not engagement_dir:
        return artifact

    cases_db = engagement_dir / "cases.db"
    surfaces_path = engagement_dir / "surfaces.jsonl"
    katana_output_path = engagement_dir / "scans" / "katana_output.jsonl"
    katana_error_path = engagement_dir / "scans" / "katana_error.log"

    artifact["files"]["cases_db_exists"] = cases_db.exists()
    artifact["files"]["surfaces_lines"] = _line_count(surfaces_path)
    artifact["files"]["katana_output_lines"] = _line_count(katana_output_path)
    artifact["files"]["katana_error_tail"] = _tail(katana_error_path)

    if not cases_db.exists():
        return artifact

    with sqlite3.connect(cases_db) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(cases)").fetchall()}
        type_rows = connection.execute(
            "SELECT type, status, COUNT(*) FROM cases GROUP BY type, status"
        ).fetchall()
        processing_rows = (
            connection.execute(
                "SELECT assigned_agent, COUNT(*) "
                "FROM cases "
                "WHERE status = 'processing' AND assigned_agent IS NOT NULL AND assigned_agent != '' "
                "GROUP BY assigned_agent"
            ).fetchall()
            if "assigned_agent" in columns
            else []
        )
        source_rows = (
            connection.execute(
                "SELECT COALESCE(source, '(unknown)'), COUNT(*) "
                "FROM cases GROUP BY 1 ORDER BY 2 DESC, 1"
            ).fetchall()
            if "source" in columns
            else []
        )
        selected_columns = [
            name for name in ("method", "url", "type", "status", "assigned_agent", "source") if name in columns
        ]
        observed_rows = (
            connection.execute(
                f"SELECT {', '.join(selected_columns)} FROM cases "
                "ORDER BY "
                "CASE WHEN status = 'processing' THEN 0 WHEN status = 'pending' THEN 1 WHEN status = 'done' THEN 2 ELSE 3 END, "
                "type, url"
            ).fetchall()
            if selected_columns
            else []
        )

    metrics = artifact["cases"]
    by_type: dict[str, Counter] = defaultdict(Counter)
    for case_type, status_name, count in type_rows:
        case_type = str(case_type or "unknown")
        status_name = str(status_name or "unknown")
        count = int(count or 0)
        by_type[case_type][status_name] += count
        metrics["total_cases"] += count
        if status_name == "done":
            metrics["completed_cases"] += count
        elif status_name == "pending":
            metrics["pending_cases"] += count
        elif status_name == "processing":
            metrics["processing_cases"] += count
        elif status_name == "error":
            metrics["error_cases"] += count

    metrics["case_types"] = [
        {
            "type": case_type,
            "total": sum(counter.values()),
            "done": counter.get("done", 0),
            "pending": counter.get("pending", 0),
            "processing": counter.get("processing", 0),
            "error": counter.get("error", 0),
        }
        for case_type, counter in sorted(by_type.items(), key=lambda item: (-sum(item[1].values()), item[0]))
    ]
    metrics["processing_agents"] = [
        {"agent_name": str(agent_name), "count": int(count)} for agent_name, count in processing_rows
    ]
    metrics["source_counts"] = [
        {"source": str(source_name), "count": int(count)} for source_name, count in source_rows
    ]

    for row in observed_rows:
        payload = dict(zip(selected_columns, row, strict=False))
        url = str(payload.get("url") or "").strip()
        if not url:
            continue
        artifact["observed_paths"].append(
            {
                "method": str(payload.get("method") or "GET").strip() or "GET",
                "url": url,
                "type": str(payload.get("type") or "unknown").strip() or "unknown",
                "status": str(payload.get("status") or "unknown").strip() or "unknown",
                "assigned_agent": str(payload.get("assigned_agent") or "").strip(),
                "source": str(payload.get("source") or "").strip(),
            }
        )

    return artifact


if len(sys.argv) != 2:
    print("usage: run_context_snapshot.py <run_id>", file=sys.stderr)
    sys.exit(2)

run_id = sys.argv[1]
summary = api_get(f"/projects/{PROJECT_ID}/runs/{run_id}/summary", {})
observed_paths = api_get(f"/projects/{PROJECT_ID}/runs/{run_id}/observed-paths", [])

target = summary.get("target") if isinstance(summary, dict) else {}
engagement_dir_text = str((target or {}).get("engagement_dir") or "").strip()
engagement_dir = Path(engagement_dir_text) if engagement_dir_text else Path()
artifact = _artifact_snapshot(engagement_dir)

api_total_cases = int(((summary.get("coverage") or {}).get("total_cases") or 0)) if isinstance(summary, dict) else 0
api_observed_total = len(observed_paths) if isinstance(observed_paths, list) else 0
artifact_total_cases = int(artifact["cases"]["total_cases"])
artifact_observed_total = len(artifact["observed_paths"])
katana_output_lines = int(artifact["files"]["katana_output_lines"])

reasons: list[str] = []
if artifact_total_cases > 0 and api_total_cases == 0:
    artifact["integrity"]["summary_api_suspicious"] = True
    reasons.append("api_summary_zero_cases_while_cases_db_has_rows")
if artifact_observed_total > 0 and api_observed_total == 0:
    artifact["integrity"]["observed_api_suspicious"] = True
    reasons.append("api_observed_paths_empty_while_cases_db_has_rows")
if katana_output_lines > 0 and api_observed_total == 0:
    artifact["integrity"]["observed_api_suspicious"] = True
    reasons.append("api_observed_paths_empty_while_katana_output_exists")
artifact["integrity"]["reasons"] = reasons

patched_summary = json.loads(json.dumps(summary)) if isinstance(summary, dict) else {}
patched_observed_paths = observed_paths if isinstance(observed_paths, list) else []
if reasons:
    coverage = patched_summary.setdefault("coverage", {})
    for key in (
        "total_cases",
        "completed_cases",
        "pending_cases",
        "processing_cases",
        "error_cases",
        "case_types",
        "processing_agents",
    ):
        coverage[key] = artifact["cases"][key]
    if artifact["files"]["surfaces_lines"] > 0 and int(coverage.get("total_surfaces") or 0) == 0:
        coverage["total_surfaces"] = artifact["files"]["surfaces_lines"]
    patched_observed_paths = artifact["observed_paths"]
    artifact["integrity"]["fallback_applied"] = True
    patched_summary.setdefault("integrity", {})
    patched_summary["integrity"].update(
        {
            "coverage_source": "artifact-fallback",
            "observed_paths_source": "artifact-fallback",
            "reasons": reasons,
        }
    )
else:
    patched_summary.setdefault("integrity", {})
    patched_summary["integrity"].update(
        {
            "coverage_source": "api",
            "observed_paths_source": "api",
            "reasons": [],
        }
    )

print(
    json.dumps(
        {
            "summary": patched_summary,
            "observed_paths": patched_observed_paths,
            "artifact": artifact,
        },
        indent=2,
    )
)
