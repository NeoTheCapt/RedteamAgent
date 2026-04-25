#!/usr/bin/env python3
"""audit_orchestrator_features.py — validate Plan 5 config injection into container env.

Usage: python3 audit_orchestrator_features.py <cycle_id>

Checks:
1. Create throwaway project with crawler_json/agents_json config.
2. Create a run for that project.
3. Verify KATANA_CRAWL_DEPTH and REDTEAM_DISABLED_AGENTS appear in the runtime env.
4. Stop run via API; verify _reconcile_run_status does NOT flip it back.

Output: local-hermes-agent/audit-reports/<cycle_id>/features.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
TEMP_PROJECT_PREFIX = "__audit-features-test__"

findings: list[dict[str, Any]] = []
pass_count = 0
fail_count = 0
_finding_seq = 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_id() -> str:
    global _finding_seq
    _finding_seq += 1
    return f"FEAT-{_finding_seq:03d}"


def record_pass(label: str) -> None:
    global pass_count
    pass_count += 1
    print(f"[PASS] {label}", file=sys.stderr)


def record_fail(label: str, severity: str, summary: str, evidence: dict[str, Any]) -> None:
    global fail_count
    fail_count += 1
    findings.append(
        {
            "id": _next_id(),
            "category": "orch_feature",
            "severity": severity,
            "summary": summary,
            "evidence": evidence,
            "suggested_fix_path": "local-hermes-agent/scripts/audit_orchestrator_features.py",
        }
    )
    print(f"[FAIL] {label}: {summary}", file=sys.stderr)


def write_report(report_path: Path, cycle_id: str) -> None:
    report = {
        "cycle_id": cycle_id,
        "source_tag": "features",
        "generated_at": _now(),
        "findings": findings,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[audit_orchestrator_features] wrote {len(findings)} findings to {report_path}", file=sys.stderr)


def extract_token_from_scheduler_env(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("ORCH_TOKEN="):
            continue
        token = line.split("=", 1)[1].strip().strip('"').strip("'")
        if token and token != "***":
            return token
    return ""


def resolve_token() -> str:
    token = os.environ.get("ORCH_TOKEN", "").strip()
    if token:
        return token
    scheduler_env = Path(
        os.environ.get(
            "LOCAL_HERMES_ENV_FILE",
            str(ROOT_DIR / "state/scheduler.env"),
        )
    )
    if not scheduler_env.exists():
        return ""
    return extract_token_from_scheduler_env(scheduler_env.read_text(encoding="utf-8"))


def build_temp_project_name(cycle_id: str, suffix: str | None = None) -> str:
    actual_suffix = suffix or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{TEMP_PROJECT_PREFIX}-{cycle_id.lower()}-{actual_suffix}"


def is_audit_temp_project(name: str) -> bool:
    return name == TEMP_PROJECT_PREFIX or name.startswith(f"{TEMP_PROJECT_PREFIX}-")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _api(base_url: str, method: str, path: str, body: dict[str, Any] | None = None, token: str = "") -> tuple[int, dict[str, Any] | list[Any] | None]:
    url = base_url + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(token) if token else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, None
    except Exception as exc:
        print(f"[_api] {method} {path} network error: {exc}", file=sys.stderr)
        return 0, None


def cleanup_stale_audit_projects(base_url: str, token: str) -> int:
    status, payload = _api(base_url, "GET", "/projects", token=token)
    if status != 200 or not isinstance(payload, list):
        return 0

    deleted = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        project_id = item.get("id")
        name = str(item.get("name") or "")
        if not isinstance(project_id, int) or not is_audit_temp_project(name):
            continue
        delete_status, _ = _api(base_url, "DELETE", f"/projects/{project_id}", token=token)
        if delete_status in (200, 202, 204, 404):
            deleted += 1
    return deleted


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: audit_orchestrator_features.py <cycle_id>", file=sys.stderr)
        return 1

    cycle_id = argv[1]
    audit_dir = ROOT_DIR / "audit-reports" / cycle_id
    report_path = audit_dir / "features.json"
    base_url = os.environ.get("ORCH_BASE_URL", "http://127.0.0.1:18000")

    token = resolve_token()
    if not token:
        record_fail(
            "token_resolve",
            "critical",
            "Could not resolve ORCH_TOKEN; cannot run features audit",
            {"hint": "set ORCH_TOKEN env var or populate scheduler.env"},
        )
        write_report(report_path, cycle_id)
        return 0

    # Preflight: if the token is stale (orchestrator restarted since last
    # cycle, session rotated, etc.) every authed call below would re-emit
    # a 401 finding that looks like a product bug. Short-circuit with one
    # sentinel "token expired" finding instead. Verified necessary after
    # cycle 20260423T023057Z.
    probe_status, _ = _api(base_url, "GET", "/auth/me", token=token)
    if probe_status != 200:
        record_fail(
            "token_valid",
            "critical",
            f"ORCH_TOKEN rejected by /auth/me (HTTP {probe_status}); skipping features audit to avoid 401-noise findings",
            {"http_status": probe_status, "hint": "rotate ORCH_TOKEN in scheduler.env"},
        )
        write_report(report_path, cycle_id)
        return 0

    deleted_stale_projects = cleanup_stale_audit_projects(base_url, token)
    if deleted_stale_projects:
        record_pass(f"stale_audit_project_cleanup ({deleted_stale_projects})")

    crawler_config = {"KATANA_CRAWL_DEPTH": 7}
    agents_config = {"fuzzer": False}
    project_name = build_temp_project_name(cycle_id)
    create_body = {
        "name": project_name,
        "provider_id": "",
        "model_id": "",
        "api_key": "",
        "base_url": "",
        "crawler_json": json.dumps(crawler_config),
        "agents_json": json.dumps(agents_config),
        "parallel_json": "{}",
    }

    project_id: int | None = None
    run_id: int | None = None

    try:
        status, proj = _api(base_url, "POST", "/projects", body=create_body, token=token)
        if status != 201 or not isinstance(proj, dict):
            record_fail(
                "project_create",
                "critical",
                f"Could not create test project (HTTP {status}); cannot test config injection",
                {"http_status": status, "response": str(proj)[:200], "project_name": project_name},
            )
            return 0

        project_id = proj.get("id")
        if not isinstance(project_id, int):
            record_fail(
                "project_create",
                "critical",
                "Project create succeeded without an integer project id",
                {"response": proj},
            )
            return 0

        record_pass(f"project_create (id={project_id})")

        try:
            crawler_returned = json.loads(proj.get("crawler_json") or "{}")
            agents_returned = json.loads(proj.get("agents_json") or "{}")
        except json.JSONDecodeError:
            crawler_returned = {}
            agents_returned = {}

        if crawler_returned.get("KATANA_CRAWL_DEPTH") == 7:
            record_pass("project_crawler_json_roundtrip")
        else:
            record_fail(
                "project_crawler_json_roundtrip",
                "high",
                "crawler_json not persisted correctly; KATANA_CRAWL_DEPTH not 7 in project response",
                {"crawler_json_returned": proj.get("crawler_json"), "expected": crawler_config},
            )

        if agents_returned.get("fuzzer") is False:
            record_pass("project_agents_json_roundtrip")
        else:
            record_fail(
                "project_agents_json_roundtrip",
                "high",
                "agents_json not persisted correctly; fuzzer:false not returned",
                {"agents_json_returned": proj.get("agents_json"), "expected": agents_config},
            )

        status_run, run = _api(
            base_url,
            "POST",
            f"/projects/{project_id}/runs",
            body={"target": "http://127.0.0.1:8000"},
            token=token,
        )
        if status_run != 201 or not isinstance(run, dict):
            record_fail(
                "run_create",
                "critical",
                f"Could not create test run (HTTP {status_run})",
                {"http_status": status_run, "project_id": project_id},
            )
            return 0

        run_id = run.get("id")
        engagement_root = str(run.get("engagement_root") or "")
        if not isinstance(run_id, int):
            record_fail(
                "run_create",
                "critical",
                "Run create succeeded without an integer run id",
                {"response": run, "project_id": project_id},
            )
            return 0

        record_pass(f"run_create (id={run_id})")

        time.sleep(3)

        env_path = Path(engagement_root) / "workspace" / ".env"
        process_env_found = False
        katana_depth_ok = False
        disabled_agents_ok = False

        if env_path.exists():
            process_env_found = True
            env_content = env_path.read_text(encoding="utf-8", errors="replace")
            for line in env_content.splitlines():
                if line.startswith("KATANA_CRAWL_DEPTH="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value == "7":
                        katana_depth_ok = True
                if line.startswith("REDTEAM_DISABLED_AGENTS="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if "fuzzer" in value.split(","):
                        disabled_agents_ok = True

        if not process_env_found:
            container_name = f"redteam-orch-run-{run_id:04d}"
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{json .Config.Env}}", container_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    env_list = json.loads(result.stdout.strip())
                    for entry in env_list:
                        if entry.startswith("KATANA_CRAWL_DEPTH="):
                            value = entry.split("=", 1)[1]
                            if value == "7":
                                katana_depth_ok = True
                        if entry.startswith("REDTEAM_DISABLED_AGENTS="):
                            value = entry.split("=", 1)[1]
                            if "fuzzer" in value.split(","):
                                disabled_agents_ok = True
                    process_env_found = True
            except Exception as exc:
                print(f"[docker inspect fallback] {exc}", file=sys.stderr)

        if not process_env_found:
            record_fail(
                "env_file_exists",
                "medium",
                "workspace/.env not written and docker inspect unavailable; cannot verify injection",
                {"engagement_root": engagement_root, "env_path": str(env_path)},
            )
        else:
            record_pass("env_file_exists")
            if katana_depth_ok:
                record_pass("env_KATANA_CRAWL_DEPTH=7")
            else:
                record_fail(
                    "env_KATANA_CRAWL_DEPTH",
                    "high",
                    "KATANA_CRAWL_DEPTH=7 not found in runtime env despite crawler_json config",
                    {"engagement_root": engagement_root, "env_path": str(env_path) if env_path.exists() else "docker_inspect"},
                )

            if disabled_agents_ok:
                record_pass("env_REDTEAM_DISABLED_AGENTS_contains_fuzzer")
            else:
                record_fail(
                    "env_REDTEAM_DISABLED_AGENTS",
                    "high",
                    "REDTEAM_DISABLED_AGENTS does not contain 'fuzzer' despite agents_json:{fuzzer:false}",
                    {"engagement_root": engagement_root},
                )

        status_stop, stop_resp = _api(
            base_url,
            "POST",
            f"/projects/{project_id}/runs/{run_id}/status",
            body={"status": "stopped"},
            token=token,
        )
        if status_stop in (200, 201) and isinstance(stop_resp, dict):
            record_pass(f"run_stop_api (returned status={stop_resp.get('status')})")
        else:
            record_fail(
                "run_stop_api",
                "medium",
                f"POST /status stopped returned HTTP {status_stop}",
                {"http_status": status_stop},
            )

        flipped_back = False
        poll_end = time.time() + 15
        while time.time() < poll_end:
            time.sleep(3)
            _, run_now = _api(base_url, "GET", f"/projects/{project_id}/runs/{run_id}/summary", token=token)
            if isinstance(run_now, dict):
                current_status = (run_now.get("target") or {}).get("status", "")
                if current_status in ("running", "queued"):
                    flipped_back = True
                    break

        if flipped_back:
            record_fail(
                "reconciler_no_flip",
                "high",
                "Run status flipped back to running/queued after being set to stopped — reconciler bug",
                {"run_id": run_id, "project_id": project_id},
            )
        else:
            record_pass("reconciler_no_flip")
    finally:
        cleanup_attempted = project_id is not None
        cleanup_errors: list[dict[str, Any]] = []
        if run_id is not None and project_id is not None:
            run_delete_status, _ = _api(base_url, "DELETE", f"/projects/{project_id}/runs/{run_id}", token=token)
            if run_delete_status not in (200, 202, 204, 404):
                cleanup_errors.append({"run_id": run_id, "http_status": run_delete_status})
        if project_id is not None:
            project_delete_status, _ = _api(base_url, "DELETE", f"/projects/{project_id}", token=token)
            if project_delete_status not in (200, 202, 204, 404):
                cleanup_errors.append({"project_id": project_id, "http_status": project_delete_status})

        if cleanup_attempted and not cleanup_errors:
            record_pass("cleanup")
        elif cleanup_errors:
            record_fail(
                "cleanup",
                "medium",
                "Audit cleanup did not fully remove temporary resources",
                {"errors": cleanup_errors},
            )

    write_report(report_path, cycle_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
