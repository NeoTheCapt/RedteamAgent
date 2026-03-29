from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import time
from threading import Thread
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.run import Run
from ..models.user import User
from ..security import create_session_token, session_expiry_timestamp


def runtime_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "runtime"


def workspace_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "workspace"


def opencode_home_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "opencode-home"


def metadata_path_for(run: Run) -> Path:
    return Path(run.engagement_root) / "run.json"


def seed_root_for(run: Run) -> Path:
    return Path(run.engagement_root) / "seed"


def process_log_path_for(run: Run) -> Path:
    return runtime_root_for(run) / "process.log"


def process_metadata_path_for(run: Run) -> Path:
    return runtime_root_for(run) / "process.json"


def runtime_container_name(run: Run) -> str:
    return f"redteam-orch-run-{run.id:04d}"


_LOOPBACK_RUNTIME_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_RUNTIME_HOST_GATEWAY_ALIAS = "host.docker.internal"


def _rewrite_runtime_target(target: str) -> str:
    stripped = (target or "").strip()
    if not stripped:
        return target

    try:
        parsed = urlsplit(stripped)
    except ValueError:
        return target

    if parsed.scheme not in {"http", "https"}:
        return target

    hostname = (parsed.hostname or "").strip().lower()
    if hostname not in _LOOPBACK_RUNTIME_HOSTS:
        return target

    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"

    if ":" in _RUNTIME_HOST_GATEWAY_ALIAS and not _RUNTIME_HOST_GATEWAY_ALIAS.startswith("["):
        host = f"[{_RUNTIME_HOST_GATEWAY_ALIAS}]"
    else:
        host = _RUNTIME_HOST_GATEWAY_ALIAS
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"

    rewritten = parsed._replace(netloc=f"{auth}{host}")
    return urlunsplit(rewritten)


def _active_engagement_dir(run: Run) -> Path | None:
    engagements_root = workspace_root_for(run) / "engagements"
    active_file = workspace_root_for(run) / "engagements" / ".active"
    if not active_file.exists():
        candidates = sorted([path for path in engagements_root.iterdir() if path.is_dir()], reverse=True) if engagements_root.exists() else []
        if candidates:
            active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
            return candidates[0]
        return None

    active_name = active_file.read_text(encoding="utf-8").strip()
    if not active_name:
        return None

    active_relative = active_name.removeprefix("./").removeprefix("/")
    if active_relative.startswith("engagements/"):
        active_dir = workspace_root_for(run) / active_relative
    else:
        active_dir = workspace_root_for(run) / "engagements" / active_relative
    if active_dir.exists():
        return active_dir
    candidates = sorted([path for path in engagements_root.iterdir() if path.is_dir()], reverse=True) if engagements_root.exists() else []
    if candidates:
        active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
        return candidates[0]
    return None


_PHASE_CANONICAL_MAP = {
    "recon": "recon",
    "collect": "collect",
    "consume-test": "consume_test",
    "consume_test": "consume_test",
    "consume and test": "consume_test",
    "test": "consume_test",
    "exploit": "exploit",
    "report": "report",
    "complete": "complete",
}


def _canonical_phase_name(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = str(value).strip().lower().replace("&", "and").replace("_", "-")
    return _PHASE_CANONICAL_MAP.get(normalized, normalized)


def _normalize_scope_file(scope_path: Path) -> dict[str, object] | None:
    if not scope_path.exists():
        return None
    try:
        payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    changed = False
    current_phase = _canonical_phase_name(payload.get("current_phase"))
    if current_phase != payload.get("current_phase"):
        payload["current_phase"] = current_phase
        changed = True

    phases_completed = payload.get("phases_completed")
    if isinstance(phases_completed, list):
        normalized = [_canonical_phase_name(item) for item in phases_completed]
        if normalized != phases_completed:
            payload["phases_completed"] = normalized
            changed = True

    if changed:
        scope_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _active_name_to_engagement_dir(workspace: Path, active_name: str) -> Path:
    active_relative = active_name.removeprefix("./").removeprefix("/")
    if active_relative.startswith("engagements/"):
        return workspace / active_relative
    return workspace / "engagements" / active_relative


def _heartbeat_context(run: Run) -> tuple[str, str]:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return ("unknown", "Runtime active; waiting for engagement initialization.")

    scope_path = engagement_dir / "scope.json"
    if not scope_path.exists():
        return ("unknown", "Runtime active; engagement created, waiting for phase details.")

    scope = _normalize_scope_file(scope_path)
    if scope is None:
        return ("unknown", "Runtime active; scope metadata is not yet readable.")

    phase = str(scope.get("current_phase") or "unknown")
    return (phase, f"Runtime active in {phase}; waiting for new agent output.")


def _count_remaining_cases(cases_db: Path) -> tuple[int, int]:
    if not cases_db.exists():
        return (0, 0)
    try:
        with sqlite3.connect(cases_db, timeout=1.0) as connection:
            connection.execute("PRAGMA busy_timeout = 1000")
            pending = connection.execute(
                "SELECT COUNT(*) FROM cases WHERE status = 'pending'"
            ).fetchone()
            processing = connection.execute(
                "SELECT COUNT(*) FROM cases WHERE status = 'processing'"
            ).fetchone()
    except sqlite3.Error:
        return (0, 0)
    return (int(pending[0] or 0), int(processing[0] or 0))


def _surface_completion_ok(surface_file: Path) -> bool:
    if not surface_file.exists():
        return True
    try:
        rows = [json.loads(line) for line in surface_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except json.JSONDecodeError:
        return False
    strict_deferred_types = {
        "account_recovery",
        "dynamic_render",
        "object_reference",
        "privileged_write",
    }
    for row in rows:
        status_name = str(row.get("status") or "").strip()
        surface_type = str(row.get("surface_type") or "").strip()
        if status_name == "discovered":
            return False
        if status_name == "deferred" and surface_type in strict_deferred_types:
            return False
    return True


def _last_logged_stop_metadata(log_path: Path) -> tuple[str, str]:
    if not log_path.exists():
        return ("", "")
    content = log_path.read_text(encoding="utf-8", errors="replace")
    headings = list(re.finditer(r"^## \[[^\]]+\] Run stop — operator\s*$", content, flags=re.MULTILINE))
    if not headings:
        return ("", "")
    section = content[headings[-1].start() :]
    action_match = re.search(r"^\*\*Action\*\*: stop_reason=([^\n]+)\s*$", section, flags=re.MULTILINE)
    result_match = re.search(r"^\*\*Result\*\*: (.+)$", section, flags=re.MULTILINE)
    reason_code = action_match.group(1).strip() if action_match else ""
    reason_text = result_match.group(1).strip() if result_match else ""
    return (reason_code, reason_text)


def _last_logged_stop_reason(log_path: Path) -> str:
    return _last_logged_stop_metadata(log_path)[1]


def engagement_completion_state(run: Run) -> tuple[bool, str]:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return (False, "No active engagement directory found.")

    scope_path = engagement_dir / "scope.json"
    report_path = engagement_dir / "report.md"
    cases_db = engagement_dir / "cases.db"
    surfaces_path = engagement_dir / "surfaces.jsonl"
    log_path = engagement_dir / "log.md"

    if not scope_path.exists():
        return (False, "scope.json is missing.")

    scope = _normalize_scope_file(scope_path)
    if scope is None:
        return (False, "scope.json is unreadable.")

    status_name = str(scope.get("status") or "").strip().lower()
    current_phase = _canonical_phase_name(scope.get("current_phase"))
    completed_phases = {_canonical_phase_name(item) for item in scope.get("phases_completed", [])}

    if status_name != "complete":
        logged_reason = _last_logged_stop_reason(log_path)
        if logged_reason:
            return (False, logged_reason)
        return (False, f"Engagement status is {status_name or 'unknown'}.")
    if current_phase != "complete":
        return (False, f"Current phase is {current_phase or 'unknown'}.")
    if "report" not in completed_phases:
        return (False, "Report phase is not marked complete.")
    if not report_path.exists():
        return (False, "report.md is missing.")

    pending_cases, processing_cases = _count_remaining_cases(cases_db)
    if pending_cases or processing_cases:
        return (
            False,
            f"Queue still has pending={pending_cases} processing={processing_cases}.",
        )

    if not _surface_completion_ok(surfaces_path):
        return (False, "Surface coverage is still unresolved.")

    return (True, "Engagement completed and finalized.")


def normalize_active_scope(run: Run) -> None:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return
    _normalize_scope_file(engagement_dir / "scope.json")


def _write_run_terminal_reason(run: Run, *, reason_code: str, reason_text: str) -> None:
    metadata_path = metadata_path_for(run)
    if not metadata_path.exists():
        return
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    payload["stop_reason_code"] = reason_code
    payload["stop_reason_text"] = reason_text
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _terminal_reason(
    *,
    succeeded: bool,
    return_code: int | None,
    completion_reason: str,
    init_only_exit: bool,
    disappeared: bool = False,
    never_started: bool = False,
) -> tuple[str, str, str]:
    if succeeded:
        return ("completed", "Run completed successfully.", "Runtime finished successfully.")
    if never_started:
        return ("runtime_never_started", "Runtime container never entered a running state.", "Runtime container stayed in created state and never started.")
    if disappeared:
        return ("runtime_disappeared", "Runtime container disappeared unexpectedly.", "Runtime container disappeared unexpectedly.")
    if return_code == 0 and completion_reason.startswith("Queue still has"):
        return ("queue_incomplete", completion_reason, f"Runtime stopped before engagement completed: {completion_reason}")
    if return_code == 0 and completion_reason == "Surface coverage is still unresolved.":
        return ("surface_coverage_incomplete", completion_reason, f"Runtime stopped before engagement completed: {completion_reason}")
    if return_code == 0 and completion_reason.startswith("Engagement status is"):
        return ("engagement_incomplete", completion_reason, f"Runtime stopped before engagement completed: {completion_reason}")
    if return_code == 0 and init_only_exit:
        return ("init_only_exit", "Runtime exited after initialization without todo setup or subagent dispatch.", "Runtime exited after initialization without todo setup or subagent dispatch.")
    if return_code == 0 and completion_reason:
        return ("incomplete_stop", completion_reason, f"Runtime stopped before engagement completed: {completion_reason}")
    return ("runtime_exit_failure", f"Runtime exited with non-zero status {return_code}.", "Runtime exited with failure.")


def _terminal_reason_from_artifacts(run: Run) -> tuple[bool, str, str, str]:
    completion_ok, completion_reason = engagement_completion_state(run)
    init_only_exit = _init_only_exit(run)
    succeeded = completion_ok and not init_only_exit
    if succeeded:
        return (succeeded, *_terminal_reason(
            succeeded=True,
            return_code=0,
            completion_reason=completion_reason,
            init_only_exit=init_only_exit,
        ))

    engagement_dir = _active_engagement_dir(run)
    queue_reason = ""
    if engagement_dir is not None:
        pending_cases, processing_cases = _count_remaining_cases(engagement_dir / "cases.db")
        if pending_cases or processing_cases:
            queue_reason = f"Queue still has pending={pending_cases} processing={processing_cases}."

    inferred_reason = queue_reason or completion_reason
    if init_only_exit or inferred_reason:
        return (succeeded, *_terminal_reason(
            succeeded=False,
            return_code=0,
            completion_reason=inferred_reason,
            init_only_exit=init_only_exit,
        ))
    return (succeeded, *_terminal_reason(
        succeeded=False,
        return_code=None,
        completion_reason=completion_reason,
        init_only_exit=init_only_exit,
        disappeared=True,
    ))


def _sync_agent_source_into_workspace(run: Run) -> None:
    source_root = Path(settings.agent_source_dir)
    workspace_root = workspace_root_for(run)
    excluded_children = {"engagements", "wal"}
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    for child in source_root.iterdir():
        if child.name in excluded_children:
            continue
        destination = workspace_root / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(child, destination)



def prepare_run_runtime(project: Project, run: Run) -> None:
    run_root = Path(run.engagement_root)
    run_root.mkdir(parents=True, exist_ok=True)
    runtime_root_for(run).mkdir(parents=True, exist_ok=True)
    _sync_agent_source_into_workspace(run)
    opencode_home_root_for(run).mkdir(parents=True, exist_ok=True)
    seed_root_for(run).mkdir(parents=True, exist_ok=True)

    if project.auth_json.strip():
        (seed_root_for(run) / "auth.json").write_text(project.auth_json + "\n", encoding="utf-8")
    elif (seed_root_for(run) / "auth.json").exists():
        (seed_root_for(run) / "auth.json").unlink()

    if project.env_json.strip():
        (seed_root_for(run) / "env.json").write_text(project.env_json + "\n", encoding="utf-8")
    elif (seed_root_for(run) / "env.json").exists():
        (seed_root_for(run) / "env.json").unlink()

    metadata = {
        "project_id": project.id,
        "project_slug": project.slug,
        "run_id": run.id,
        "target": run.target,
        "status": run.status,
        "engagement_root": run.engagement_root,
        "runtime_root": str(runtime_root_for(run)),
        "workspace_root": str(workspace_root_for(run)),
        "opencode_home_root": str(opencode_home_root_for(run)),
        "seed_root": str(seed_root_for(run)),
        "agent_source_dir": str(settings.agent_source_dir),
        "process_log": str(process_log_path_for(run)),
    }
    metadata_path_for(run).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _runtime_env(project: Project, run: Run, user: User) -> dict[str, str]:
    token = create_session_token()
    db.create_session(user.id, token, session_expiry_timestamp())
    env = os.environ.copy()
    env.update(
        {
            "OPENCODE_HOME": str(opencode_home_root_for(run)),
            "ORCHESTRATOR_BASE_URL": settings.orchestrator_container_url,
            "ORCHESTRATOR_TOKEN": token,
            "ORCHESTRATOR_PROJECT_ID": str(project.id),
            "ORCHESTRATOR_RUN_ID": str(run.id),
        }
    )
    provider_id = project.provider_id.strip().lower()
    model_id = project.model_id.strip()
    small_model_id = project.small_model_id.strip()
    api_key = project.api_key.strip()
    base_url = project.base_url.strip()

    if provider_id and model_id:
        env["REDTEAM_OPENCODE_MODEL"] = f"{provider_id}/{model_id}"
    elif model_id:
        env["REDTEAM_OPENCODE_MODEL"] = model_id

    if provider_id and small_model_id:
        env["REDTEAM_OPENCODE_SMALL_MODEL"] = f"{provider_id}/{small_model_id}"
    elif small_model_id:
        env["REDTEAM_OPENCODE_SMALL_MODEL"] = small_model_id

    if provider_id == "openai":
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        if model_id:
            env["OPENAI_MODEL"] = model_id
    elif provider_id == "anthropic":
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
        if model_id:
            env["ANTHROPIC_MODEL"] = model_id
    elif provider_id in {"openrouter", "openai-compatible"}:
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        if model_id:
            env["OPENAI_MODEL"] = model_id

    if project.env_json.strip():
        try:
            env_payload = json.loads(project.env_json)
        except json.JSONDecodeError:
            env_payload = {}
        if isinstance(env_payload, dict):
            for key, value in env_payload.items():
                if not isinstance(key, str):
                    continue
                if value is None:
                    continue
                env[key] = str(value)
    return env


def _append_runtime_event(run: Run, event_type: str, phase: str, summary: str) -> None:
    try:
        db.create_event(run.id, event_type, phase, "runtime", "launcher", summary)
    except Exception:
        return


def _write_process_metadata(run: Run, process: subprocess.Popen[bytes]) -> None:
    metadata = {
        "run_id": run.id,
        "container_name": runtime_container_name(run),
        "command": [
            "docker",
            "run",
            "--rm",
            "--name",
            runtime_container_name(run),
            settings.redteam_allinone_image,
            "opencode",
            "run",
            "--format",
            "json",
            f"/autoengage {run.target}",
        ],
        "started_at": db.get_run_by_id(run.id).updated_at if db.get_run_by_id(run.id) else None,
    }
    pid = getattr(process, "pid", None)
    if isinstance(pid, int):
        metadata["pid"] = pid
    process_metadata_path_for(run).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_SENSITIVE_ENV_PATTERN = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASS|COOKIE|AUTH)", re.IGNORECASE)


def _redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    idx = 0
    while idx < len(command):
        part = command[idx]
        redacted.append(part)
        if part == "-e" and idx + 1 < len(command):
            env_assignment = command[idx + 1]
            if "=" in env_assignment:
                key, _, value = env_assignment.partition("=")
                if _SENSITIVE_ENV_PATTERN.search(key):
                    redacted.append(f"{key}=<redacted>")
                else:
                    redacted.append(env_assignment)
            else:
                redacted.append(env_assignment)
            idx += 2
            continue
        idx += 1
    return redacted


def _write_container_metadata(run: Run, container_id: str, command: list[str]) -> None:
    metadata = {
        "run_id": run.id,
        "container_name": runtime_container_name(run),
        "container_id": container_id,
        "command": _redact_command(command),
        "started_at": db.get_run_by_id(run.id).updated_at if db.get_run_by_id(run.id) else None,
        "launcher_pid": os.getpid(),
    }
    process_metadata_path_for(run).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _init_only_exit(run: Run) -> bool:
    process_log = process_log_path_for(run)
    if not process_log.exists():
        return True
    saw_subagent_task = False
    saw_todo = False
    for line in process_log.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "tool_use":
            continue
        part = payload.get("part") or {}
        tool_name = part.get("tool")
        state = part.get("state") or {}
        task_input = state.get("input") or {}
        if tool_name == "task" and task_input.get("subagent_type"):
            saw_subagent_task = True
        if tool_name in {"todowrite", "todoread"}:
            saw_todo = True
    return not (saw_subagent_task or saw_todo)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _container_name_from_metadata(run: Run) -> str | None:
    metadata_path = process_metadata_path_for(run)
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if int(payload.get("run_id", -1)) != run.id:
        return None
    container_name = payload.get("container_name")
    return container_name if isinstance(container_name, str) and container_name else None


def _container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_status(container_name: str) -> str | None:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    status = result.stdout.strip()
    return status or None


def _container_exit_code(container_name: str) -> int | None:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def locate_runtime_pid(run: Run) -> int | None:
    metadata_path = process_metadata_path_for(run)
    payload: dict[str, object] = {}
    if metadata_path.exists():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}

    if int(payload.get("run_id", -1)) == run.id:
        try:
            pid = int(payload.get("pid"))
            if _pid_alive(pid):
                return pid
        except (ValueError, TypeError):
            pass

    container_name = payload.get("container_name")
    if not isinstance(container_name, str) or not container_name:
        container_name = _container_name_from_metadata(run)
    if container_name:
        status = _container_status(container_name)
        if status in {"running", "restarting"}:
            return -1
        if status == "created":
            try:
                launcher_pid = int(payload.get("launcher_pid"))
            except (ValueError, TypeError):
                launcher_pid = None
            if launcher_pid == os.getpid():
                return -1
            return None
        if status is not None:
            return None

    try:
        output = subprocess.check_output(["ps", "eww", "-axo", "pid=,command="], text=True)
    except subprocess.SubprocessError:
        return None

    needle = f"ORCHESTRATOR_RUN_ID={run.id}"
    for line in output.splitlines():
        if needle not in line:
            continue
        pid_text, _, _ = line.strip().partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if _pid_alive(pid):
            process_metadata_path_for(run).write_text(
                json.dumps({"pid": pid, "run_id": run.id, "command": line.strip()}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return pid
    return None


def stop_run_runtime(run: Run) -> None:
    container_name = _container_name_from_metadata(run)
    if container_name:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    pid = locate_runtime_pid(run)
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    workspace = workspace_root_for(run)
    active_file = workspace / "engagements" / ".active"
    if active_file.exists():
        active_name = active_file.read_text(encoding="utf-8").strip()
        if active_name:
            engagement_dir = _active_name_to_engagement_dir(workspace, active_name)
            if engagement_dir.exists():
                subprocess.run(
                    [
                        "bash",
                        "-lc",
                        "source scripts/lib/container.sh && export ENGAGEMENT_DIR=\"$1\" && stop_all_containers",
                        "bash",
                        str(engagement_dir),
                    ],
                    cwd=str(workspace),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )


def _supervise_process(run: Run, process: subprocess.Popen[bytes], log_handle, heartbeat_interval: int = 5) -> None:
    while True:
        try:
            return_code = process.wait(timeout=heartbeat_interval)
            break
        except subprocess.TimeoutExpired:
            phase, summary = _heartbeat_context(run)
            _append_runtime_event(run, "run.heartbeat", phase, summary)

    log_handle.close()
    phase, summary = _heartbeat_context(run)
    completion_ok, completion_reason = engagement_completion_state(run)
    init_only_exit = _init_only_exit(run)
    succeeded = return_code == 0 and not init_only_exit and completion_ok
    reason_code, reason_text, summary = _terminal_reason(
        succeeded=succeeded,
        return_code=return_code,
        completion_reason=completion_reason,
        init_only_exit=init_only_exit,
    )
    _append_runtime_event(
        run,
        "run.completed" if succeeded else "run.failed",
        phase,
        summary,
    )
    terminal = db.update_run_status(run.id, "completed" if succeeded else "failed")
    _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)


def _supervise_container(
    run: Run,
    container_name: str,
    log_follower: subprocess.Popen[bytes] | None,
    log_handle,
    heartbeat_interval: int = 5,
    startup_grace_seconds: int = 20,
) -> None:
    startup_deadline = time.time() + startup_grace_seconds
    while True:
        status = _container_status(container_name)
        if status in {"running", "restarting"}:
            phase, summary = _heartbeat_context(run)
            _append_runtime_event(run, "run.heartbeat", phase, summary)
            time.sleep(heartbeat_interval)
            continue
        if status == "created":
            if time.time() < startup_deadline:
                time.sleep(1)
                continue
            reason_code, reason_text, summary = _terminal_reason(
                succeeded=False,
                return_code=None,
                completion_reason="",
                init_only_exit=False,
                never_started=True,
            )
            _append_runtime_event(run, "run.failed", "initializing", summary)
            terminal = db.update_run_status(run.id, "failed")
            _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)
            break
        if status == "exited":
            exit_code = _container_exit_code(container_name)
            phase, _ = _heartbeat_context(run)
            completion_ok, completion_reason = engagement_completion_state(run)
            init_only_exit = _init_only_exit(run)
            succeeded = exit_code == 0 and not init_only_exit and completion_ok
            reason_code, reason_text, summary = _terminal_reason(
                succeeded=succeeded,
                return_code=exit_code,
                completion_reason=completion_reason,
                init_only_exit=init_only_exit,
            )
            _append_runtime_event(
                run,
                "run.completed" if succeeded else "run.failed",
                phase,
                summary,
            )
            terminal = db.update_run_status(run.id, "completed" if succeeded else "failed")
            _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)
            break
        if status is None:
            phase, _ = _heartbeat_context(run)
            succeeded, reason_code, reason_text, summary = _terminal_reason_from_artifacts(run)
            _append_runtime_event(run, "run.completed" if succeeded else "run.failed", phase, summary)
            terminal = db.update_run_status(run.id, "completed" if succeeded else "failed")
            _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)
            break
        time.sleep(heartbeat_interval)

    if log_follower is not None and log_follower.poll() is None:
        log_follower.terminate()
        try:
            log_follower.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log_follower.kill()
    log_handle.close()


def start_run_runtime(project: Project, run: Run, user: User) -> Run:
    prepare_run_runtime(project, run)
    process_log_path_for(run).parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(process_log_path_for(run), "ab")

    try:
        subprocess.run(
            ["docker", "rm", "-f", runtime_container_name(run)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        runtime_env = _runtime_env(project, run, user)
        passthrough_keys = [
            "REDTEAM_OPENCODE_MODEL",
            "REDTEAM_OPENCODE_SMALL_MODEL",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "LOG_LEVEL",
        ]
        env_args = [
            "-e",
            f"ORCHESTRATOR_BASE_URL={runtime_env['ORCHESTRATOR_BASE_URL']}",
            "-e",
            f"ORCHESTRATOR_TOKEN={runtime_env['ORCHESTRATOR_TOKEN']}",
            "-e",
            f"ORCHESTRATOR_PROJECT_ID={runtime_env['ORCHESTRATOR_PROJECT_ID']}",
            "-e",
            f"ORCHESTRATOR_RUN_ID={runtime_env['ORCHESTRATOR_RUN_ID']}",
        ]
        for key in passthrough_keys:
            value = runtime_env.get(key)
            if value:
                env_args.extend(["-e", f"{key}={value}"])

        runtime_target = _rewrite_runtime_target(run.target)
        docker_command = [
            "docker",
            "run",
            "-d",
            "--name",
            runtime_container_name(run),
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{workspace_root_for(run)}:/workspace",
            "-v",
            f"{opencode_home_root_for(run)}:/root/.local/share/opencode",
            *env_args,
            settings.redteam_allinone_image,
            "opencode",
            "run",
            "--format",
            "json",
            f"/autoengage {runtime_target}",
        ]
        result = subprocess.run(
            docker_command,
            cwd=str(run.engagement_root),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_output = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_output or "docker run failed")
        container_id = (result.stdout or "").strip()
        _write_container_metadata(run, container_id, docker_command)
        log_follower = subprocess.Popen(
            ["docker", "logs", "-f", runtime_container_name(run)],
            cwd=str(run.engagement_root),
            env=os.environ.copy(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        log_handle.write(f"launcher failed: {exc!r}\n".encode("utf-8"))
        log_handle.close()
        return db.update_run_status(run.id, "failed")

    running = db.update_run_status(run.id, "running")
    _append_runtime_event(running, "run.started", "initializing", "Runtime launched; waiting for agent activity.")
    Thread(target=_supervise_container, args=(running, runtime_container_name(run), log_follower, log_handle), daemon=True).start()
    return running
