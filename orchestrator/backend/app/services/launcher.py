from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock, Thread
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from .. import db
from ..config import settings
from ..models.project import Project
from ..models.run import Run
from ..models.user import User
from ..security import create_session_token, session_expiry_timestamp


_ACTIVE_CONTAINER_SUPERVISORS: dict[int, object] = {}
_ACTIVE_CONTAINER_SUPERVISORS_LOCK = Lock()


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


RUNTIME_PID_CONTAINER = -1
RUNTIME_PID_LOOKUP_UNAVAILABLE = -2
_CONTAINER_STATUS_LOOKUP_UNAVAILABLE = "__lookup_unavailable__"


_LOOPBACK_RUNTIME_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_RUNTIME_HOST_GATEWAY_ALIAS = "host.docker.internal"


def _normalize_auth_payload(raw: str) -> str:
    payload: dict[str, object]
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    payload = parsed if isinstance(parsed, dict) else {}

    cookies = payload.get("cookies") if isinstance(payload.get("cookies"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    discovered = payload.get("discovered_credentials") if isinstance(payload.get("discovered_credentials"), list) else []
    validated = payload.get("validated_credentials") if isinstance(payload.get("validated_credentials"), list) else []
    legacy = payload.get("credentials") if isinstance(payload.get("credentials"), list) else []

    merged_legacy: list[object] = []
    seen: set[str] = set()
    for item in [*discovered, *validated, *legacy]:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker in seen:
            continue
        seen.add(marker)
        merged_legacy.append(item)

    normalized = dict(payload)
    normalized["cookies"] = cookies
    normalized["headers"] = headers
    normalized["tokens"] = tokens
    normalized["discovered_credentials"] = discovered or legacy
    normalized["validated_credentials"] = validated
    normalized["credentials"] = merged_legacy
    return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


_AUTO_RESUME_REASON_CODES = {
    "engagement_incomplete",
    "incomplete_stop",
    "queue_incomplete",
    "queue_stalled",
    "surface_coverage_incomplete",
    # A missing supervisor/container can still leave a perfectly resumable
    # in-progress engagement behind (for example after a backend restart or a
    # detached launcher thread). Allow bounded /resume recovery for that case
    # instead of hard-failing an otherwise healthy queue.
    "runtime_disappeared",
}
_AUTO_RESUME_LIMIT = 3

RUN_STALL_TIMEOUT_SECONDS = 900
PROCESSING_AGENT_MISMATCH_GRACE_SECONDS = 120
PENDING_QUEUE_DISPATCH_GRACE_SECONDS = 120
PERMISSION_REQUEST_GRACE_SECONDS = 60
# Real targets can spend several minutes in autonomous initialization/recon before the
# first queue item or observed path lands. Keep the live launcher watchdog aligned with
# the API reconciler so we do not fail healthy slow-start recon while subagent dispatch
# is still warming up.
EARLY_PHASE_STALL_TIMEOUT_SECONDS = 300
EARLY_PHASE_STALL_PHASES = {"unknown", "recon", "collect"}


def _is_sqlite_corruption_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("malformed", "not a database", "disk image is malformed"))


def _is_sqlite_transient_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("locked", "busy", "database schema is locked"))


def _connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.execute("PRAGMA busy_timeout = 1000")
    return connection


def _copy_sqlite_snapshot(path: Path, snapshot_dir: Path) -> Path:
    snapshot_path = snapshot_dir / path.name
    shutil.copy2(path, snapshot_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, snapshot_dir / sidecar.name)
    return snapshot_path


def _read_sqlite_snapshot(path: Path, reader, default):
    try:
        with tempfile.TemporaryDirectory(prefix="launcher-sqlite-") as temp_dir:
            snapshot_path = _copy_sqlite_snapshot(path, Path(temp_dir))
            with _connect_sqlite_readonly(snapshot_path) as connection:
                return reader(connection)
    except (OSError, sqlite3.Error):
        return default


def _read_sqlite_with_fallback(path: Path, reader, default):
    if not path.exists():
        return default

    for _ in range(5):
        try:
            with sqlite3.connect(path, timeout=1.0) as connection:
                connection.execute("PRAGMA busy_timeout = 1000")
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc) and not _is_sqlite_corruption_error(exc):
                return default
        except sqlite3.Error as exc:
            if not _is_sqlite_corruption_error(exc):
                return default

        try:
            with _connect_sqlite_readonly(path) as connection:
                return reader(connection)
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_transient_error(exc) and not _is_sqlite_corruption_error(exc):
                return default
        except sqlite3.Error as exc:
            if not _is_sqlite_corruption_error(exc):
                return default

        snapshot_value = _read_sqlite_snapshot(path, reader, default)
        if snapshot_value is not default:
            return snapshot_value

        time.sleep(0.1)

    return default


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


def _engagement_dir_rank(path: Path) -> tuple[int, float, str]:
    return (1 if (path / "scope.json").exists() else 0, path.stat().st_mtime, path.name)



def _active_engagement_dir(run: Run) -> Path | None:
    workspace = workspace_root_for(run)
    engagements_root = workspace / "engagements"
    active_file = engagements_root / ".active"
    if not active_file.exists():
        candidates = (
            sorted(
                [path for path in engagements_root.iterdir() if path.is_dir()],
                key=_engagement_dir_rank,
                reverse=True,
            )
            if engagements_root.exists()
            else []
        )
        if candidates:
            active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
            return candidates[0]
        return None

    active_name = active_file.read_text(encoding="utf-8").strip()
    if not active_name:
        return None

    active_path = Path(active_name)
    if active_path.is_absolute():
        if active_path.exists() and (active_path / "scope.json").exists():
            return active_path
    else:
        active_relative = active_name.removeprefix("./").removeprefix("/")
        if active_relative.startswith("engagements/"):
            active_dir = workspace / active_relative
        else:
            active_dir = engagements_root / active_relative
        if active_dir.exists() and (active_dir / "scope.json").exists():
            return active_dir

    candidates = (
        sorted(
            [path for path in engagements_root.iterdir() if path.is_dir()],
            key=_engagement_dir_rank,
            reverse=True,
        )
        if engagements_root.exists()
        else []
    )
    if candidates:
        active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
        return candidates[0]
    if active_path.is_absolute() and active_path.exists():
        return active_path
    if 'active_dir' in locals() and active_dir.exists():
        return active_dir
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


def _loopback_display_context(run: Run | None) -> dict[str, str] | None:
    if run is None:
        return None

    stripped = str(run.target or "").strip()
    if not stripped:
        return None

    try:
        parsed = urlsplit(stripped)
    except ValueError:
        return None

    hostname = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or hostname not in _LOOPBACK_RUNTIME_HOSTS:
        return None

    alias_netloc = _RUNTIME_HOST_GATEWAY_ALIAS
    if parsed.port is not None:
        alias_netloc = f"{alias_netloc}:{parsed.port}"

    return {
        "target": stripped,
        "target_base": urlunsplit((parsed.scheme, parsed.netloc, "", "", "")),
        "target_host": parsed.hostname or hostname,
        "alias_host": _RUNTIME_HOST_GATEWAY_ALIAS,
        "alias_base": urlunsplit((parsed.scheme, alias_netloc, "", "", "")),
    }


def _rewrite_loopback_text(value: str, context: dict[str, str] | None) -> str:
    if not value or context is None:
        return value

    rewritten = value.replace(context["alias_base"], context["target_base"])
    rewritten = rewritten.replace(f"*.{context['alias_host']}", f"*.{context['target_host']}")
    rewritten = rewritten.replace(context["alias_host"], context["target_host"])
    return rewritten


def _is_sensitive_header_name(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return False
    return normalized in {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-xsrf-token",
    }


def _rewrite_artifact_value(value, context: dict[str, str] | None, *, redact_headers: bool = False):
    if isinstance(value, dict):
        rewritten: dict[object, object] = {}
        for key, item in value.items():
            key_name = str(key or "")
            lower_key = key_name.strip().lower()
            if redact_headers and lower_key == "headers" and isinstance(item, dict):
                sanitized_headers = {}
                for header_name, header_value in item.items():
                    if _is_sensitive_header_name(str(header_name)):
                        sanitized_headers[header_name] = "<redacted>"
                    else:
                        sanitized_headers[header_name] = _rewrite_artifact_value(header_value, context, redact_headers=redact_headers)
                rewritten[key] = sanitized_headers
                continue
            rewritten[key] = _rewrite_artifact_value(item, context, redact_headers=redact_headers)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_artifact_value(item, context, redact_headers=redact_headers) for item in value]
    if isinstance(value, str):
        return _rewrite_loopback_text(value, context)
    return value


def _canonical_scope_status(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == "completed":
        return "complete"
    return normalized


def _should_persist_loopback_rewrite(run: Run | None) -> bool:
    return run is None or run.status in {"failed", "completed"}


def _normalize_scope_file(scope_path: Path, *, run: Run | None = None) -> dict[str, object] | None:
    if not scope_path.exists():
        return None
    try:
        payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    changed = False
    status_name = _canonical_scope_status(payload.get("status"))
    if status_name and status_name != payload.get("status"):
        payload["status"] = status_name
        changed = True

    current_phase = _canonical_phase_name(payload.get("current_phase"))
    if current_phase != payload.get("current_phase"):
        payload["current_phase"] = current_phase
        changed = True

    phases_completed = payload.get("phases_completed")
    if isinstance(phases_completed, list):
        normalized: list[str] = []
        seen_phases: set[str] = set()
        for item in phases_completed:
            phase_name = _canonical_phase_name(item)
            if phase_name in seen_phases:
                changed = True
                continue
            normalized.append(phase_name)
            seen_phases.add(phase_name)
        if normalized != phases_completed:
            payload["phases_completed"] = normalized
            changed = True

    if status_name == "complete" and not str(payload.get("end_time") or "").strip():
        ended_at = str(getattr(run, "updated_at", "") or "").strip()
        if ended_at:
            try:
                parsed_end_time = datetime.strptime(ended_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                parsed_end_time = None
            if parsed_end_time is not None:
                payload["end_time"] = parsed_end_time.isoformat(timespec="seconds").replace("+00:00", "Z")
                changed = True

    disk_payload = payload
    context = _loopback_display_context(run)
    returned_payload = _rewrite_artifact_value(payload, context)
    if returned_payload != payload and _should_persist_loopback_rewrite(run):
        disk_payload = returned_payload
        changed = True

    if changed:
        scope_path.write_text(json.dumps(disk_payload, indent=2) + "\n", encoding="utf-8")
    return returned_payload


def _active_name_to_engagement_dir(workspace: Path, active_name: str) -> Path:
    active_path = Path(active_name)
    if active_path.is_absolute():
        return active_path

    active_relative = active_name.removeprefix("./").removeprefix("/")
    if active_relative.startswith("engagements/"):
        return workspace / active_relative
    return workspace / "engagements" / active_relative


def _heartbeat_phase_from_run_metadata(run: Run) -> tuple[str, float | None]:
    metadata_path = metadata_path_for(run)
    if not metadata_path.exists():
        return ("unknown", None)

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("unknown", _path_mtime(metadata_path))

    phase = _canonical_phase_name(payload.get("current_phase"))
    return (phase, _path_mtime(metadata_path))


def _heartbeat_context(run: Run) -> tuple[str, str]:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return ("unknown", "Runtime active; waiting for engagement initialization.")

    scope_path = engagement_dir / "scope.json"
    metadata_phase, metadata_mtime = _heartbeat_phase_from_run_metadata(run)
    if not scope_path.exists():
        phase = metadata_phase if metadata_phase != "unknown" else "unknown"
        if phase == "unknown":
            return ("unknown", "Runtime active; engagement created, waiting for phase details.")
        return (phase, f"Runtime active in {phase}; waiting for new agent output.")

    scope = _normalize_scope_file(scope_path, run=run)
    if scope is None:
        phase = metadata_phase if metadata_phase != "unknown" else "unknown"
        if phase == "unknown":
            return ("unknown", "Runtime active; scope metadata is not yet readable.")
        return (phase, f"Runtime active in {phase}; waiting for new agent output.")

    scope_phase = _canonical_phase_name(scope.get("current_phase"))
    scope_mtime = _path_mtime(scope_path)

    if metadata_phase != "unknown" and (scope_phase == "unknown" or (metadata_mtime or 0) >= (scope_mtime or 0)):
        phase = metadata_phase
    else:
        phase = scope_phase

    return (phase, f"Runtime active in {phase}; waiting for new agent output.")


def _count_remaining_cases(cases_db: Path) -> tuple[int, int]:
    def _reader(connection: sqlite3.Connection) -> tuple[int, int]:
        pending = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'pending'"
        ).fetchone()
        processing = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'processing'"
        ).fetchone()
        return (int(pending[0] or 0), int(processing[0] or 0))

    return _read_sqlite_with_fallback(cases_db, _reader, (0, 0))


def _path_mtime(path: Path) -> float | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _parse_runtime_activity_timestamp(value: object) -> float | None:
    if isinstance(value, (int, float)):
        candidate = float(value)
        if candidate > 1_000_000_000_000:
            candidate /= 1000.0
        return candidate if candidate > 0 else None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _iter_runtime_activity_timestamps(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"timestamp", "created_at", "updated_at", "started_at", "ended_at", "completed_at"}:
                parsed = _parse_runtime_activity_timestamp(value)
                if parsed is not None:
                    yield parsed
            yield from _iter_runtime_activity_timestamps(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_runtime_activity_timestamps(item)


_TEXT_LOG_TIMESTAMP_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b")
_TEXT_LOG_TIMESTAMP_OPTIONAL_TZ_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b|\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)\b")
_FETCH_BATCH_BLOCK_PATTERN = re.compile(r"(?ms)^BATCH_FILE=.*?(?=^BATCH_FILE=|\Z)")
_FETCH_BATCH_COUNT_PATTERN = re.compile(r"(?m)^BATCH_COUNT=(\d+)\s*$")
_FETCH_BATCH_AGENT_PATTERN = re.compile(r"(?m)^BATCH_AGENT=([^\n]+)\s*$")
_FETCH_BATCH_TYPE_PATTERN = re.compile(r"(?m)^BATCH_TYPE=([^\n]+)\s*$")
_FETCH_BATCH_IDS_PATTERN = re.compile(r"(?m)^BATCH_IDS=([^\n]+)\s*$")
_SUBAGENT_SESSION_TITLE_PATTERN = re.compile(r"title=.*?\(@(?P<agent>[A-Za-z0-9_-]+) subagent\)")
_SUBAGENT_STREAM_PATTERN = re.compile(r"service=llm\b.*?\bagent=(?P<agent>[A-Za-z0-9_-]+)\b.*?\bmode=subagent\b")
_SUBAGENT_SESSION_ID_PATTERN = re.compile(r"\b(?:id|sessionID)=(?P<session>ses_[A-Za-z0-9]+)\b")
_INLINE_SESSION_CREATED_AT_PATTERN = re.compile(r'"created":\s*(\d{10,13})')
_PERMISSION_REQUEST_ID_PATTERN = re.compile(r"\bid=(per_[A-Za-z0-9]+)\b")
_PERMISSION_REQUEST_RESOLVED_PATTERN = re.compile(r"\b(approved|allowed|granted|denied|rejected|cancel(?:led)?|resolved|answered|completed)\b", re.IGNORECASE)
_RUNTIME_ACTIVITY_FUTURE_SKEW_SECONDS = 5 * 60


def _runtime_activity_candidate_is_valid(candidate: float | None) -> bool:
    if candidate is None:
        return False
    if candidate <= 0:
        return False
    return candidate <= time.time() + _RUNTIME_ACTIVITY_FUTURE_SKEW_SECONDS


def _latest_process_log_activity_at(path: Path, *, max_lines: int = 400) -> float | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = deque(handle, maxlen=max_lines)
    except OSError:
        return None

    latest = None
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                for candidate in _iter_runtime_activity_timestamps(payload):
                    if not _runtime_activity_candidate_is_valid(candidate):
                        continue
                    if latest is None or candidate > latest:
                        latest = candidate
                continue

        text_match = _TEXT_LOG_TIMESTAMP_PATTERN.search(stripped)
        if text_match is None:
            continue
        candidate = _parse_runtime_activity_timestamp(text_match.group(1))
        if _runtime_activity_candidate_is_valid(candidate) and (latest is None or candidate > latest):
            latest = candidate

    if latest is not None:
        return latest
    return _path_mtime(path)


def _latest_unresolved_permission_request_at(*paths: Path, max_lines: int = 800) -> float | None:
    pending_requests: dict[str, float] = {}

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                lines = deque(handle, maxlen=max_lines)
        except OSError:
            continue

        for raw_line in lines:
            stripped = raw_line.strip()
            if "service=permission" not in stripped:
                continue
            request_match = _PERMISSION_REQUEST_ID_PATTERN.search(stripped)
            if request_match is None:
                continue
            request_id = request_match.group(1)
            line_timestamp = _extract_text_log_timestamp(stripped)
            if " asking" in stripped:
                if _runtime_activity_candidate_is_valid(line_timestamp):
                    pending_requests[request_id] = float(line_timestamp)
                continue
            if request_id in pending_requests and _PERMISSION_REQUEST_RESOLVED_PATTERN.search(stripped):
                pending_requests.pop(request_id, None)

    if not pending_requests:
        return None
    return max(pending_requests.values())



def _latest_nonempty_fetch_from_output(candidate_output: str) -> dict[str, object] | None:
    latest_fetch: dict[str, object] | None = None
    for block_match in _FETCH_BATCH_BLOCK_PATTERN.finditer(candidate_output):
        block = block_match.group(0)
        batch_count_match = _FETCH_BATCH_COUNT_PATTERN.search(block)
        batch_agent_match = _FETCH_BATCH_AGENT_PATTERN.search(block)
        batch_type_match = _FETCH_BATCH_TYPE_PATTERN.search(block)
        batch_ids_match = _FETCH_BATCH_IDS_PATTERN.search(block)
        if batch_count_match is None or batch_agent_match is None or batch_type_match is None:
            continue
        try:
            batch_count = int(batch_count_match.group(1))
        except ValueError:
            continue
        if batch_count <= 0:
            continue
        agent_name = batch_agent_match.group(1).strip()
        batch_type = batch_type_match.group(1).strip()
        if not agent_name or not batch_type:
            continue
        latest_fetch = {
            "agent": agent_name,
            "batch_type": batch_type,
            "batch_count": batch_count,
            "batch_ids": batch_ids_match.group(1).strip() if batch_ids_match else "",
        }
    return latest_fetch



def _extract_text_log_timestamp(line: str) -> float | None:
    timestamp_match = _TEXT_LOG_TIMESTAMP_OPTIONAL_TZ_PATTERN.search(line)
    if timestamp_match is None:
        return None
    raw_timestamp = timestamp_match.group(1) or timestamp_match.group(2)
    if not raw_timestamp:
        return None
    return _parse_runtime_activity_timestamp(raw_timestamp)



def _opencode_logs_active_subagent_agents(
    log_root: Path,
    *,
    active_window_seconds: int = RUN_STALL_TIMEOUT_SECONDS,
) -> set[str]:
    if not log_root.exists() or not log_root.is_dir():
        return set()

    session_agents: dict[str, str] = {}
    session_last_activity: dict[str, float] = {}
    active_sessions: set[str] = set()
    now = time.time()

    def _remember_session_activity(session_id: str, candidate: float | None) -> None:
        if not session_id or not _runtime_activity_candidate_is_valid(candidate):
            return
        previous = session_last_activity.get(session_id)
        if previous is None or float(candidate) > previous:
            session_last_activity[session_id] = float(candidate)

    for path in sorted(log_root.glob("*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue

                    line_timestamp = _extract_text_log_timestamp(stripped)

                    if "service=session.prompt" in stripped and (
                        "exiting loop" in stripped or stripped.endswith(" cancel") or " cancel" in stripped
                    ):
                        match = _SUBAGENT_SESSION_ID_PATTERN.search(stripped)
                        if match is not None:
                            session_id = match.group("session")
                            _remember_session_activity(session_id, line_timestamp)
                            active_sessions.discard(session_id)
                        continue

                    if "service=llm" in stripped and "mode=subagent" in stripped:
                        stream_match = _SUBAGENT_STREAM_PATTERN.search(stripped)
                        session_match = _SUBAGENT_SESSION_ID_PATTERN.search(stripped)
                        if stream_match is not None and session_match is not None:
                            session_id = session_match.group("session")
                            session_agents[session_id] = stream_match.group("agent")
                            _remember_session_activity(session_id, line_timestamp)
                            active_sessions.add(session_id)
                        continue

                    if "title=" in stripped and "subagent" in stripped and "created" in stripped:
                        title_match = _SUBAGENT_SESSION_TITLE_PATTERN.search(stripped)
                        session_match = _SUBAGENT_SESSION_ID_PATTERN.search(stripped)
                        if title_match is not None and session_match is not None:
                            session_id = session_match.group("session")
                            session_agents[session_id] = title_match.group("agent")
                            created_match = _INLINE_SESSION_CREATED_AT_PATTERN.search(stripped)
                            created_timestamp = None
                            if created_match is not None:
                                try:
                                    raw_created = int(created_match.group(1))
                                except ValueError:
                                    raw_created = 0
                                if raw_created > 0:
                                    created_timestamp = raw_created / 1000 if raw_created >= 10**12 else float(raw_created)
                            _remember_session_activity(session_id, created_timestamp or line_timestamp)
                            active_sessions.add(session_id)
        except OSError:
            continue

    active_agents: set[str] = set()
    for session_id in active_sessions:
        agent_name = session_agents.get(session_id)
        last_activity = session_last_activity.get(session_id)
        if not agent_name or last_activity is None:
            continue
        if now - last_activity > active_window_seconds:
            continue
        active_agents.add(agent_name)
    return active_agents



def _opencode_logs_show_subagent_activity(
    log_root: Path,
    *,
    agent_name: str,
    since_at: float,
    max_lines_per_file: int = 2000,
) -> bool:
    if not agent_name or not log_root.exists() or not log_root.is_dir():
        return False

    for path in sorted(log_root.glob("*.log"), reverse=True):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                lines = deque(handle, maxlen=max_lines_per_file)
        except OSError:
            continue

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue

            candidate = None
            matched_agent = ""

            if "title=" in stripped and "subagent" in stripped and "created" in stripped:
                match = _SUBAGENT_SESSION_TITLE_PATTERN.search(stripped)
                if match is None:
                    continue
                matched_agent = match.group("agent")
                created_match = _INLINE_SESSION_CREATED_AT_PATTERN.search(stripped)
                if created_match is not None:
                    try:
                        raw_created = int(created_match.group(1))
                    except ValueError:
                        raw_created = 0
                    if raw_created > 0:
                        candidate = raw_created / 1000 if raw_created >= 10**12 else float(raw_created)
            elif "service=llm" in stripped and "mode=subagent" in stripped:
                match = _SUBAGENT_STREAM_PATTERN.search(stripped)
                if match is None:
                    continue
                matched_agent = match.group("agent")

            if matched_agent != agent_name:
                continue

            if candidate is None:
                candidate = _extract_text_log_timestamp(stripped)
            if candidate is not None and candidate < since_at:
                continue
            return True

    return False



def _latest_undispatched_batch_fetch(
    path: Path,
    *,
    opencode_logs_root: Path | None = None,
    max_lines: int = 400,
) -> dict[str, object] | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = deque(handle, maxlen=max_lines)
    except OSError:
        return None

    latest_fetch: dict[str, object] | None = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "tool_use":
            continue

        part = payload.get("part") or {}
        state = part.get("state") or {}
        tool_name = str(part.get("tool") or "").strip()
        event_at = _parse_runtime_activity_timestamp(payload.get("timestamp"))
        if event_at is None:
            for candidate in _iter_runtime_activity_timestamps(payload):
                if _runtime_activity_candidate_is_valid(candidate):
                    event_at = candidate
                    break

        if tool_name == "task":
            task_input = state.get("input") or {}
            subagent_type = str(task_input.get("subagent_type") or "").strip()
            if (
                latest_fetch is not None
                and subagent_type
                and subagent_type == latest_fetch.get("agent")
                and (event_at is None or event_at >= float(latest_fetch.get("timestamp") or 0))
            ):
                latest_fetch = None
            continue

        if tool_name != "bash":
            continue

        state_metadata = state.get("metadata") or {}
        output_candidates = [state.get("output"), state_metadata.get("output")]
        for candidate_output in output_candidates:
            if not isinstance(candidate_output, str) or "BATCH_COUNT=" not in candidate_output:
                continue
            fetch_summary = _latest_nonempty_fetch_from_output(candidate_output)
            if fetch_summary is None:
                continue
            latest_fetch = {
                "timestamp": event_at or 0.0,
                **fetch_summary,
            }
            break

    if (
        latest_fetch is not None
        and opencode_logs_root is not None
        and _opencode_logs_show_subagent_activity(
            opencode_logs_root,
            agent_name=str(latest_fetch.get("agent") or "").strip(),
            since_at=float(latest_fetch.get("timestamp") or 0.0),
        )
    ):
        return None

    return latest_fetch


def _latest_running_runtime_activity_at(run: Run) -> float | None:
    latest = _latest_process_log_activity_at(process_log_path_for(run))

    # Ignore process.json mtime here. Launcher/recovery code may rewrite metadata
    # without any new runtime output, and using that timestamp would let a stuck
    # container look healthy forever.
    opencode_logs_root = opencode_home_root_for(run) / "log"
    if opencode_logs_root.exists():
        for path in opencode_logs_root.glob("*.log"):
            candidate = _latest_process_log_activity_at(path)
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate

    return latest


def _latest_running_workflow_activity_at(engagement_dir: Path | None) -> float | None:
    if engagement_dir is None:
        return None

    latest = None
    for path in (
        engagement_dir / "scope.json",
        engagement_dir / "log.md",
        engagement_dir / "findings.md",
        engagement_dir / "report.md",
    ):
        candidate = _path_mtime(path)
        if candidate is None:
            continue
        if latest is None or candidate > latest:
            latest = candidate
    return latest


def _load_running_queue_state(engagement_dir: Path | None) -> tuple[str, int, int, int]:
    current_phase = "unknown"
    total_cases = 0
    pending_cases = 0
    processing_cases = 0
    if engagement_dir is None:
        return (current_phase, total_cases, pending_cases, processing_cases)

    scope_path = engagement_dir / "scope.json"
    if scope_path.exists():
        try:
            scope_payload = json.loads(scope_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            scope_payload = {}
        current_phase = _canonical_phase_name(scope_payload.get("current_phase"))

    cases_db = engagement_dir / "cases.db"
    if not cases_db.exists():
        return (current_phase, total_cases, pending_cases, processing_cases)

    def _reader(connection: sqlite3.Connection) -> tuple[int, int, int]:
        total_row = connection.execute("SELECT COUNT(*) FROM cases").fetchone()
        pending_row = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'pending'"
        ).fetchone()
        processing_row = connection.execute(
            "SELECT COUNT(*) FROM cases WHERE status = 'processing'"
        ).fetchone()
        return (
            int(total_row[0] or 0),
            int(pending_row[0] or 0),
            int(processing_row[0] or 0),
        )

    total_cases, pending_cases, processing_cases = _read_sqlite_with_fallback(
        cases_db,
        _reader,
        (0, 0, 0),
    )
    return (current_phase, total_cases, pending_cases, processing_cases)


def _load_running_processing_agents(engagement_dir: Path | None) -> set[str]:
    if engagement_dir is None:
        return set()

    cases_db = engagement_dir / "cases.db"
    if not cases_db.exists():
        return set()

    def _reader(connection: sqlite3.Connection) -> list[str]:
        rows = connection.execute(
            "SELECT DISTINCT assigned_agent FROM cases WHERE status = 'processing'"
        ).fetchall()
        return [str(row[0] or "").strip() for row in rows]

    raw_agents = _read_sqlite_with_fallback(cases_db, _reader, [])
    return {agent for agent in raw_agents if agent}


def _stale_processing_agents(
    engagement_dir: Path | None,
    active_runtime_agents: set[str],
    *,
    stale_after_seconds: int = PROCESSING_AGENT_MISMATCH_GRACE_SECONDS,
) -> set[str]:
    if engagement_dir is None:
        return set()

    cases_db = engagement_dir / "cases.db"
    if not cases_db.exists():
        return set()

    def _reader(connection: sqlite3.Connection) -> list[tuple[str, str | None]]:
        column_rows = connection.execute("PRAGMA table_info(cases)").fetchall()
        column_names = {str(row[1]) for row in column_rows if len(row) > 1}
        if "assigned_agent" not in column_names or "consumed_at" not in column_names:
            return []
        rows = connection.execute(
            "SELECT assigned_agent, consumed_at FROM cases WHERE status = 'processing' AND assigned_agent IS NOT NULL"
        ).fetchall()
        return [(str(row[0] or "").strip(), str(row[1] or "").strip() or None) for row in rows]

    rows = _read_sqlite_with_fallback(cases_db, _reader, [])
    if not rows:
        return set()

    now = time.time()
    latest_consumed_at: dict[str, float] = {}
    for agent_name, consumed_at in rows:
        if not agent_name or agent_name in active_runtime_agents:
            continue
        parsed = _parse_runtime_activity_timestamp(consumed_at)
        if not _runtime_activity_candidate_is_valid(parsed):
            continue
        latest = latest_consumed_at.get(agent_name)
        if latest is None or float(parsed) > latest:
            latest_consumed_at[agent_name] = float(parsed)

    return {
        agent_name
        for agent_name, consumed_at in latest_consumed_at.items()
        if (now - consumed_at) >= stale_after_seconds
    }


def _recover_orphaned_processing_cases(run: Run, engagement_dir: Path | None) -> tuple[int, set[str]]:
    if engagement_dir is None:
        return (0, set())

    cases_db = engagement_dir / "cases.db"
    if not cases_db.exists():
        return (0, set())

    processing_agents = _load_running_processing_agents(engagement_dir)
    if not processing_agents:
        return (0, set())

    active_runtime_agents = _active_runtime_agents(run)
    orphaned_agents = processing_agents.difference(active_runtime_agents)
    if not orphaned_agents:
        return (0, set())

    try:
        with sqlite3.connect(cases_db, timeout=5.0) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            column_rows = connection.execute("PRAGMA table_info(cases)").fetchall()
            column_names = {str(row[1]) for row in column_rows if len(row) > 1}
            if "assigned_agent" not in column_names:
                return (0, set())

            set_clauses = ["status = 'pending'", "assigned_agent = NULL"]
            if "consumed_at" in column_names:
                set_clauses.append("consumed_at = NULL")

            placeholders = ", ".join("?" for _ in orphaned_agents)
            cursor = connection.execute(
                f"UPDATE cases SET {', '.join(set_clauses)} "
                f"WHERE status = 'processing' AND assigned_agent IN ({placeholders})",
                tuple(sorted(orphaned_agents)),
            )
            connection.commit()
            recovered = int(cursor.rowcount or 0)
            return (recovered, orphaned_agents if recovered > 0 else set())
    except sqlite3.Error:
        return (0, set())



def _active_runtime_metadata_agents(run: Run) -> set[str]:
    payload = _read_run_metadata(run)
    active_agents: set[str] = set()
    now = time.time()
    for item in payload.get("agents") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() != "active":
            continue
        # run.json agent cards are also used by the UI and may synthesize
        # queue-backed "active" agents from processing cases even when no live
        # task/runtime event exists. Those synthetic cards intentionally have an
        # empty updated_at. Launcher stall recovery must only treat agents with
        # substantive and recent runtime activity as active, otherwise stale
        # queue-backed cards can mask orphaned processing forever.
        updated_at = _parse_runtime_activity_timestamp(item.get("updated_at"))
        if not _runtime_activity_candidate_is_valid(updated_at):
            continue
        if (now - float(updated_at)) > PROCESSING_AGENT_MISMATCH_GRACE_SECONDS:
            continue
        agent_name = str(item.get("agent_name") or item.get("task_name") or "").strip()
        if agent_name:
            active_agents.add(agent_name)
    return active_agents



def _active_runtime_agents(run: Run) -> set[str]:
    active_agents = _active_runtime_metadata_agents(run)
    active_agents.update(_opencode_logs_active_subagent_agents(opencode_home_root_for(run) / "log"))
    return active_agents


def _run_metadata_has_current_task(run: Run) -> bool:
    payload = _read_run_metadata(run)
    current_task_name = str(payload.get("current_task_name") or "").strip()
    current_agent_name = str(payload.get("current_agent_name") or "").strip()
    return bool(current_task_name or current_agent_name)


def _latest_runtime_metadata_activity_at(run: Run) -> float | None:
    payload = _read_run_metadata(run)
    latest = None
    for candidate in _iter_runtime_activity_timestamps(payload):
        if not _runtime_activity_candidate_is_valid(candidate):
            continue
        if latest is None or candidate > latest:
            latest = candidate
    return latest


def _running_container_stall_reason(run: Run) -> tuple[str, str, str] | None:
    engagement_dir = _active_engagement_dir(run)
    current_phase, total_cases, pending_cases, processing_cases = _load_running_queue_state(engagement_dir)

    workflow_activity_at = _latest_running_workflow_activity_at(engagement_dir)
    workflow_age = (time.time() - workflow_activity_at) if workflow_activity_at is not None else None
    if workflow_age is not None:
        if (
            current_phase not in EARLY_PHASE_STALL_PHASES
            and processing_cases > 0
            and workflow_age >= RUN_STALL_TIMEOUT_SECONDS
        ):
            return (
                current_phase,
                "queue_stalled",
                "Workflow produced no new process/log progress before stall timeout elapsed while queue items remained in processing.",
            )
        if (
            current_phase not in EARLY_PHASE_STALL_PHASES
            and pending_cases > 0
            and processing_cases == 0
            and workflow_age >= RUN_STALL_TIMEOUT_SECONDS
        ):
            return (
                current_phase,
                "queue_stalled",
                "Workflow produced no new dispatch/log progress before stall timeout elapsed while pending queue items remained undispatched.",
            )

    runtime_activity_at = _latest_running_runtime_activity_at(run)
    metadata_activity_at = _latest_runtime_metadata_activity_at(run)
    active_runtime_agents = _active_runtime_agents(run)
    has_current_task = _run_metadata_has_current_task(run)
    processing_agents = _load_running_processing_agents(engagement_dir)
    opencode_logs_root = opencode_home_root_for(run) / "log"
    permission_log_paths = [process_log_path_for(run)]
    if opencode_logs_root.exists():
        permission_log_paths.extend(sorted(opencode_logs_root.glob("*.log")))
    latest_permission_request_at = _latest_unresolved_permission_request_at(*permission_log_paths)
    orphaned_fetch = _latest_undispatched_batch_fetch(
        process_log_path_for(run),
        opencode_logs_root=opencode_logs_root,
    )
    if (
        current_phase not in EARLY_PHASE_STALL_PHASES
        and latest_permission_request_at is not None
        and (time.time() - latest_permission_request_at) >= PERMISSION_REQUEST_GRACE_SECONDS
    ):
        return (
            current_phase,
            "queue_stalled",
            "Autonomous runtime requested interactive permission approval and never resolved it; unattended runs must stay within workspace-local inputs or fail fast instead of waiting forever.",
        )

    if (
        current_phase not in EARLY_PHASE_STALL_PHASES
        and pending_cases > 0
        and processing_cases == 0
        and not active_runtime_agents
        and workflow_age is not None
        and workflow_age >= PENDING_QUEUE_DISPATCH_GRACE_SECONDS
    ):
        return (
            current_phase,
            "queue_stalled",
            "Pending queue items remained undispatched with no active runtime agent after dispatch grace period elapsed.",
        )

    if (
        current_phase not in EARLY_PHASE_STALL_PHASES
        and orphaned_fetch is not None
        and str(orphaned_fetch.get("agent") or "") in processing_agents
        and str(orphaned_fetch.get("agent") or "") not in active_runtime_agents
        and (time.time() - float(orphaned_fetch.get("timestamp") or 0.0)) >= PROCESSING_AGENT_MISMATCH_GRACE_SECONDS
    ):
        batch_type = str(orphaned_fetch.get("batch_type") or "queue")
        agent_name = str(orphaned_fetch.get("agent") or "agent")
        batch_ids = str(orphaned_fetch.get("batch_ids") or "").strip()
        reason = f"Fetched non-empty {batch_type} batch for {agent_name}"
        if batch_ids:
            reason += f" (ids: {batch_ids})"
        reason += " but no matching task dispatch followed before stall grace period elapsed."
        return (
            current_phase,
            "queue_stalled",
            reason,
        )

    orphan_activity_at = metadata_activity_at
    if workflow_activity_at is not None and (
        orphan_activity_at is None or workflow_activity_at > orphan_activity_at
    ):
        orphan_activity_at = workflow_activity_at
    if (
        current_phase not in EARLY_PHASE_STALL_PHASES
        and total_cases > 0
        and pending_cases == 0
        and processing_cases == 0
        and not active_runtime_agents
        and not has_current_task
        and orphan_activity_at is not None
        and (time.time() - orphan_activity_at) >= RUN_STALL_TIMEOUT_SECONDS
    ):
        return (
            current_phase,
            "queue_stalled",
            f"Run remained in {current_phase.replace('_', '-')} with no active runtime agent, current task, or queued work before stall timeout elapsed.",
        )

    stale_processing_agents = _stale_processing_agents(engagement_dir, active_runtime_agents)
    if current_phase not in EARLY_PHASE_STALL_PHASES and stale_processing_agents:
        assigned = ", ".join(sorted(stale_processing_agents))
        if active_runtime_agents:
            active = ", ".join(sorted(active_runtime_agents))
            reason = (
                f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                f"after stall grace period elapsed (active agents: {active})."
            )
        else:
            reason = (
                f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                "after stall grace period elapsed."
            )
        return (
            current_phase,
            "queue_stalled",
            reason,
        )

    if runtime_activity_at is not None:
        runtime_age = time.time() - runtime_activity_at
        mismatch_activity_at = runtime_activity_at
        if workflow_activity_at is not None and workflow_activity_at > mismatch_activity_at:
            mismatch_activity_at = workflow_activity_at
        mismatch_age = time.time() - mismatch_activity_at
        if (
            current_phase not in EARLY_PHASE_STALL_PHASES
            and processing_agents
            and mismatch_age >= PROCESSING_AGENT_MISMATCH_GRACE_SECONDS
            and processing_agents.isdisjoint(active_runtime_agents)
        ):
            assigned = ", ".join(sorted(processing_agents))
            if active_runtime_agents:
                active = ", ".join(sorted(active_runtime_agents))
                reason = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    f"after stall grace period elapsed (active agents: {active})."
                )
            else:
                reason = (
                    f"Processing queue assignments ({assigned}) had no matching active runtime agent "
                    "after stall grace period elapsed."
                )
            return (
                current_phase,
                "queue_stalled",
                reason,
            )
        if runtime_age >= RUN_STALL_TIMEOUT_SECONDS:
            return (
                current_phase,
                "queue_stalled",
                "Runtime produced no new output before stall timeout elapsed.",
            )

    early_phase_activity_at = runtime_activity_at
    if workflow_activity_at is not None and (
        early_phase_activity_at is None or workflow_activity_at > early_phase_activity_at
    ):
        early_phase_activity_at = workflow_activity_at

    if (
        current_phase in EARLY_PHASE_STALL_PHASES
        and total_cases == 0
        and early_phase_activity_at is not None
        and (time.time() - early_phase_activity_at) >= EARLY_PHASE_STALL_TIMEOUT_SECONDS
    ):
        return (
            current_phase,
            "recon_stalled",
            "Runtime stalled in early recon/collect without producing any observed paths.",
        )
    return None


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


_REPORT_REQUIRED_SECTIONS = (
    "## Executive Summary",
    "## Scope and Methodology",
    "## Findings",
    "## Attack Narrative",
    "## Recommendations",
    "## Appendix",
)
_FINDING_SECTION_PATTERN = re.compile(
    r"^## \[(?P<id>[^\]]+)\] (?P<title>.+?)\n(?P<body>.*?)(?=^## \[|\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
_FINDING_FIELD_PATTERN = re.compile(r"^- \*\*(?P<key>[^*]+)\*\*: (?P<value>.*)$", flags=re.MULTILINE)
_FINDING_SORT_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def _report_has_substantive_content(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) < 400:
        return False
    matched_sections = sum(1 for section in _REPORT_REQUIRED_SECTIONS if section in stripped)
    if matched_sections < 4:
        return False
    if "## Findings" not in stripped:
        return False
    if re.search(r"^### \[FINDING-\d{3}\] ", stripped, flags=re.MULTILINE):
        return True
    return "No confirmed findings" in stripped


def _parse_findings_markdown(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for match in _FINDING_SECTION_PATTERN.finditer(text):
        payload: dict[str, str] = {
            "original_id": match.group("id").strip(),
            "title": match.group("title").strip(),
            "body": match.group("body").strip(),
        }
        for field in _FINDING_FIELD_PATTERN.finditer(payload["body"]):
            key = field.group("key").strip().lower().replace(" ", "_")
            payload[key] = field.group("value").strip()
        findings.append(payload)
    findings.sort(key=lambda item: (_FINDING_SORT_ORDER.get(item.get("severity", "INFO").upper(), 99), item.get("original_id", "")))
    return findings


def _severity_summary(findings: list[dict[str, str]]) -> dict[str, int]:
    counts = {severity: 0 for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")}
    for finding in findings:
        severity = str(finding.get("severity") or "INFO").upper()
        counts[severity if severity in counts else "INFO"] += 1
    return counts


def _overall_risk_label(counts: dict[str, int]) -> str:
    if counts.get("CRITICAL"):
        return "Critical"
    if counts.get("HIGH"):
        return "High"
    if counts.get("MEDIUM"):
        return "Moderate"
    if counts.get("LOW"):
        return "Low"
    return "Informational"


def _format_scope_timeframe(scope: dict[str, object] | None) -> str:
    if not isinstance(scope, dict):
        return "Timeframe unavailable"
    start = str(scope.get("start_time") or scope.get("started_at") or "").strip()
    end = str(scope.get("end_time") or "").strip()
    if start and end:
        return f"{start} → {end}"
    if start:
        return f"Started {start}"
    return "Timeframe unavailable"


def _extract_findings_report_paths(findings: list[dict[str, str]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        evidence = str(finding.get("evidence") or "")
        for candidate in re.findall(r"(?:engagements/[^\s`'\"]+|downloads/[^\s`'\"]+|scans/[^\s`'\"]+)", evidence):
            if candidate in seen:
                continue
            seen.add(candidate)
            paths.append(candidate)
            if len(paths) >= 8:
                return paths
    return paths


def _synthesize_completion_report(engagement_dir: Path, scope: dict[str, object] | None) -> None:
    report_path = engagement_dir / "report.md"
    findings_path = engagement_dir / "findings.md"
    findings_text = findings_path.read_text(encoding="utf-8", errors="replace") if findings_path.exists() else ""
    findings = _parse_findings_markdown(findings_text)
    counts = _severity_summary(findings)
    total_findings = sum(counts.values())

    target = ""
    scope_entries: list[str] = []
    phases_completed: list[str] = []
    if isinstance(scope, dict):
        target = str(scope.get("target") or "").strip()
        scope_entries = [str(item).strip() for item in scope.get("scope") or [] if str(item).strip()]
        phases_completed = [str(item).strip() for item in scope.get("phases_completed") or [] if str(item).strip()]

    evidence_paths = _extract_findings_report_paths(findings)
    cases_db = engagement_dir / "cases.db"
    total_cases = 0
    if cases_db.exists():
        try:
            with sqlite3.connect(cases_db) as connection:
                row = connection.execute("SELECT COUNT(*) FROM cases").fetchone()
            total_cases = int(row[0]) if row else 0
        except sqlite3.Error:
            total_cases = 0

    surface_count = 0
    surfaces_path = engagement_dir / "surfaces.jsonl"
    if surfaces_path.exists():
        surface_count = sum(1 for line in surfaces_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())

    methodology_steps = []
    if phases_completed:
        methodology_steps.append(f"Completed phases: {', '.join(phases_completed)}")
    if total_cases:
        methodology_steps.append(f"Processed {total_cases} queued cases from crawler and follow-up analysis.")
    if surface_count:
        methodology_steps.append(f"Tracked {surface_count} observed surfaces in surfaces.jsonl.")
    if not methodology_steps:
        methodology_steps.append("Completed the orchestrated reconnaissance, analysis, and reporting workflow using recorded engagement artifacts only.")

    recommendations: list[str] = []
    if counts.get("CRITICAL") or counts.get("HIGH"):
        recommendations.append("Prioritize the highest-severity exposures first, especially issues that enable account compromise, secret leakage, or direct access to sensitive files or privileged workflows.")
    if any(finding.get("severity", "").upper() in {"MEDIUM", "HIGH", "CRITICAL"} and "Authentication" in str(finding.get("owasp_category") or "") for finding in findings):
        recommendations.append("Review authentication and authorization boundaries on privileged API routes and workflow/state tokens; require explicit auth checks instead of trusting client-visible identifiers or setup material.")
    if any("stack trace" in str(finding.get("title") or "").lower() or "exposure" in str(finding.get("type") or "").lower() for finding in findings):
        recommendations.append("Disable verbose production error disclosure and trim sensitive response fields so diagnostic paths do not expose stack traces, hashes, tokens, or internal file locations.")
    if not recommendations:
        recommendations.append("Continue monitoring newly discovered surfaces and keep validating that crawler-derived coverage stays aligned with the recorded findings and queue output.")

    executive_lines = [
        f"- Target: `{target or 'unknown'}`",
        f"- Timeframe: {_format_scope_timeframe(scope)}",
        f"- Confirmed findings: {total_findings} total ({counts['CRITICAL']} critical / {counts['HIGH']} high / {counts['MEDIUM']} medium / {counts['LOW']} low / {counts['INFO']} info)",
        f"- Overall risk assessment: {_overall_risk_label(counts)}",
    ]

    scope_lines = []
    if scope_entries:
        scope_lines.append(f"- Scope entries: {', '.join(scope_entries)}")
    else:
        scope_lines.append(f"- Scope entries: {target or 'Unavailable'}")
    scope_lines.extend(f"- {line}" for line in methodology_steps)

    findings_blocks: list[str] = []
    if findings:
        for index, finding in enumerate(findings, start=1):
            finding_id = f"FINDING-{index:03d}"
            findings_blocks.append(
                "\n".join(
                    [
                        f"### [{finding_id}] {finding.get('title', 'Untitled finding')}",
                        f"- **Original ID**: {finding.get('original_id', '')}",
                        f"- **Severity**: {finding.get('severity', 'INFO')}",
                        f"- **OWASP Category**: {finding.get('owasp_category', 'Unspecified')}",
                        f"- **Type**: {finding.get('type', 'Unspecified')}",
                        f"- **Location**: {finding.get('parameter', 'Unspecified')}",
                        f"- **Description**: Derived from the recorded finding `{finding.get('original_id', '')}` and its linked evidence in `findings.md`.",
                        "- **Evidence**:",
                        f"  - {finding.get('evidence', 'See findings.md for the recorded proof.')}",
                        f"- **Impact**: {finding.get('impact', 'Impact not captured in the finding record.')}",
                        "- **Remediation**: Address the exposed condition at the affected route/component and re-test the documented evidence path after the fix.",
                    ]
                )
            )
    else:
        findings_blocks.append("No confirmed findings were recorded in `findings.md`.")

    attack_narrative = (
        "The engagement followed the recorded orchestrator workflow from reconnaissance into targeted source and vulnerability analysis, then consolidated confirmed evidence into the final report. "
        "The report content below was synthesized directly from `scope.json`, `findings.md`, `cases.db`, `surfaces.jsonl`, and the engagement log because the original report artifact was missing or incomplete at completion time."
    )
    if not findings:
        attack_narrative += " No multi-step attack paths identified."

    appendix_lines = [
        f"- cases.db rows: {total_cases}",
        f"- surfaces.jsonl rows: {surface_count}",
        "- Referenced artifact files:",
    ]
    if evidence_paths:
        appendix_lines.extend(f"  - `{path}`" for path in evidence_paths)
    else:
        appendix_lines.append("  - `findings.md`")
        appendix_lines.append("  - `log.md`")

    serialized_scope = json.dumps(scope or {}, indent=2)
    scope_label = ", ".join(scope_entries) if scope_entries else (target or "Unavailable")
    report_text = "\n\n".join(
        [
            "# Penetration Test Report",
            f"**Date**: {_engagement_header_date(scope)} — Completed\n**Target**: {target or 'unknown'}  **Scope**: {scope_label}  **Status**: Completed",
            "## Executive Summary\n" + "\n".join(executive_lines),
            "## Scope and Methodology\n" + "\n".join(scope_lines),
            "## Findings\n" + "\n\n".join(findings_blocks),
            f"## Attack Narrative\n{attack_narrative}",
            "## Recommendations\n" + "\n".join(f"- {item}" for item in recommendations),
            "## Appendix\n" + "\n".join(appendix_lines) + f"\n\n### C. Full scope.json\n```json\n{serialized_scope}\n```",
        ]
    ).rstrip() + "\n"
    report_path.write_text(report_text, encoding="utf-8")


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

    scope = _normalize_scope_file(scope_path, run=run)
    if scope is None:
        return (False, "scope.json is unreadable.")

    status_name = _canonical_scope_status(scope.get("status"))
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
    report_text = report_path.read_text(encoding="utf-8", errors="replace")
    if not _report_has_substantive_content(report_text):
        return (False, "report.md is incomplete.")

    pending_cases, processing_cases = _count_remaining_cases(cases_db)
    if pending_cases or processing_cases:
        return (
            False,
            f"Queue still has pending={pending_cases} processing={processing_cases}.",
        )

    if not _surface_completion_ok(surfaces_path):
        return (False, "Surface coverage is still unresolved.")

    return (True, "Engagement completed and finalized.")


def _normalize_text_artifact(path: Path, context: dict[str, str] | None) -> None:
    if context is None or not path.exists():
        return
    original = path.read_text(encoding="utf-8", errors="replace")
    rewritten = _rewrite_loopback_text(original, context)
    if rewritten != original:
        path.write_text(rewritten, encoding="utf-8")


def _engagement_header_date(scope: dict[str, object] | None) -> str:
    if isinstance(scope, dict):
        raw_start_time = str(scope.get("start_time") or "").strip()
        if raw_start_time:
            try:
                parsed = datetime.fromisoformat(raw_start_time.replace("Z", "+00:00"))
                return parsed.astimezone().strftime("%Y-%m-%d")
            except ValueError:
                pass
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _normalize_log_completion_artifact(path: Path) -> None:
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8", errors="replace")
    rewritten = re.sub(
        r"^- \*\*Status\*\*:.*$",
        "- **Status**: Completed",
        original,
        count=1,
        flags=re.MULTILINE,
    )
    if rewritten != original:
        path.write_text(rewritten, encoding="utf-8")


def _replace_report_scope_snapshot(text: str, scope: dict[str, object] | None) -> str:
    if not isinstance(scope, dict):
        return text
    serialized_scope = json.dumps(scope, indent=2)
    return re.sub(
        r"(### C\. Full scope\.json\s*```json\n)(.*?)(\n```)",
        lambda match: f"{match.group(1)}{serialized_scope}{match.group(3)}",
        text,
        count=1,
        flags=re.DOTALL,
    )


def _normalize_report_completion_artifact(path: Path, *, header_date: str, scope: dict[str, object] | None) -> None:
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8", errors="replace")
    trailing_newline = original.endswith("\n")
    lines = original.splitlines()
    changed = False
    date_found = False

    for index, line in enumerate(lines):
        if line.startswith("**Date**:"):
            normalized = f"**Date**: {header_date} — Completed"
            if line != normalized:
                lines[index] = normalized
                changed = True
            date_found = True
            continue
        if line.startswith("**Target**:"):
            if "**Status**:" in line:
                normalized = re.sub(r"\*\*Status\*\*: .*", "**Status**: Completed", line, count=1)
            else:
                normalized = f"{line}  **Status**: Completed"
            if line != normalized:
                lines[index] = normalized
                changed = True
            continue
        if line.startswith("**Status**:"):
            normalized = "**Status**: Completed"
            if line != normalized:
                lines[index] = normalized
                changed = True

    if not date_found:
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, f"**Date**: {header_date} — Completed")
        changed = True

    rewritten = "\n".join(lines)
    rewritten = _replace_report_scope_snapshot(rewritten, scope)
    if rewritten == original and not changed:
        return

    if trailing_newline:
        rewritten += "\n"
    path.write_text(rewritten, encoding="utf-8")


def _normalize_completion_artifacts(engagement_dir: Path, scope: dict[str, object] | None) -> None:
    if not isinstance(scope, dict):
        return
    if _canonical_scope_status(scope.get("status")) != "complete":
        return
    header_date = _engagement_header_date(scope)
    report_path = engagement_dir / "report.md"
    existing_report = report_path.read_text(encoding="utf-8", errors="replace") if report_path.exists() else ""
    if not _report_has_substantive_content(existing_report):
        _synthesize_completion_report(engagement_dir, scope)
    _normalize_log_completion_artifact(engagement_dir / "log.md")
    _normalize_report_completion_artifact(report_path, header_date=header_date, scope=scope)


_JSONL_DISALLOWED_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_jsonl_text(value: str) -> str:
    if not value:
        return value
    return _JSONL_DISALLOWED_CONTROL_CHARS.sub("", value)


def _decode_json_stream(value: str) -> list[object] | None:
    stripped = value.strip()
    if not stripped:
        return []

    decoder = json.JSONDecoder()
    payloads: list[object] = []
    remaining = stripped

    while remaining:
        try:
            payload, index = decoder.raw_decode(remaining)
        except json.JSONDecodeError:
            return None
        payloads.append(payload)
        remaining = remaining[index:].lstrip()

    return payloads


def _normalize_jsonl_artifact(
    path: Path,
    context: dict[str, str] | None,
    *,
    redact_headers: bool = False,
    preserve_malformed: bool = False,
) -> None:
    if not path.exists() or (context is None and not redact_headers):
        return

    original = path.read_text(encoding="utf-8", errors="replace")
    trailing_newline = original.endswith("\n")
    rewritten_lines: list[str] = []
    changed = False

    for line in original.splitlines():
        stripped = line.strip()
        if not stripped:
            rewritten_lines.append(line)
            continue

        sanitized = _sanitize_jsonl_text(line)
        payloads = _decode_json_stream(sanitized)
        if payloads is None:
            rewritten_line = _rewrite_loopback_text(sanitized, context)
            if preserve_malformed:
                if rewritten_line != line:
                    changed = True
                rewritten_lines.append(rewritten_line)
            else:
                if re.match(r"^https?://", stripped):
                    if rewritten_line != line:
                        changed = True
                    rewritten_lines.append(rewritten_line)
                else:
                    changed = True
            continue

        if len(payloads) != 1 or sanitized != line:
            changed = True
        for payload in payloads:
            rewritten_payload = _rewrite_artifact_value(payload, context, redact_headers=redact_headers)
            rewritten_line = json.dumps(rewritten_payload, separators=(",", ":"))
            if len(payloads) == 1 and rewritten_line != line:
                changed = True
            rewritten_lines.append(rewritten_line)

    if changed:
        rewritten = "\n".join(rewritten_lines)
        if trailing_newline:
            rewritten += "\n"
        path.write_text(rewritten, encoding="utf-8")


def _normalize_cases_db(path: Path, context: dict[str, str] | None) -> None:
    if context is None or not path.exists():
        return
    try:
        with sqlite3.connect(path, timeout=1.0) as connection:
            connection.execute("PRAGMA busy_timeout = 1000")
            column_rows = connection.execute("PRAGMA table_info(cases)").fetchall()
            column_names = {str(row[1]) for row in column_rows}
            if "id" not in column_names or "url" not in column_names:
                return
            rows = connection.execute("SELECT id, url FROM cases").fetchall()
            changed = False
            for row_id, raw_url in rows:
                url = str(raw_url or "")
                rewritten = _rewrite_loopback_text(url, context)
                if rewritten == url:
                    continue
                connection.execute("UPDATE cases SET url = ? WHERE id = ?", (rewritten, row_id))
                changed = True
            if changed:
                connection.commit()
    except sqlite3.Error:
        return


_SURFACE_AGENT_PREFIX = re.compile(r"^\[[^\]]+\]\s*")
_SURFACE_PLACEHOLDER_PATTERN = re.compile(r"(%3c[^/%\s]+%3e|<[^>\s]+>|FUZZ|PARAM|\{\{|\}\})", re.IGNORECASE)
_SURFACE_HTTP_METHOD_PATTERN = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")
_VALID_SURFACE_TYPES = {
    "auth_entry",
    "account_recovery",
    "object_reference",
    "privileged_write",
    "file_handling",
    "dynamic_render",
    "api_documentation",
    "workflow_token",
    "api_param_followup",
    "cors_review",
}
_VALID_SURFACE_STATUSES = {"discovered", "covered", "not_applicable", "deferred"}
_SURFACE_TYPE_ALIASES = {
    "spa_route": "dynamic_render",
    "spa": "dynamic_render",
    "client_route": "dynamic_render",
    "client_side_route": "dynamic_render",
    "frontend_route": "dynamic_render",
    "auth_workflow": "account_recovery",
    "identity_verification": "auth_entry",
    "p2p_trading": "dynamic_render",
    "web3_assets": "dynamic_render",
    "preview_or_internal_content": "dynamic_render",
    "file": "file_handling",
    "upload": "file_handling",
    "api_docs": "api_documentation",
    "swagger": "api_documentation",
    "openapi": "api_documentation",
    "auth": "auth_entry",
    "authentication": "auth_entry",
    "login": "auth_entry",
    "register": "auth_entry",
    "mfa": "auth_entry",
    "oauth": "auth_entry",
    "oauth_flow": "auth_entry",
    "auth_surface": "auth_entry",
    "anti_automation": "auth_entry",
    "broken_anti_automation": "auth_entry",
    "business_logic": "privileged_write",
    "logic_flow": "privileged_write",
    "stateful_flow": "privileged_write",
    "race_condition": "privileged_write",
    "update_distribution": "file_handling",
    "cors_surface": "cors_review",
    "opaque_post_contract": "api_param_followup",
    "opaque_post_body": "api_param_followup",
    "body_contract": "api_param_followup",
    "schema_followup": "api_param_followup",
}


def _normalize_surface_type(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return _SURFACE_TYPE_ALIASES.get(normalized, normalized)


def _infer_surface_type(method: str, target: str, item_type: str, auth_hint: str, rationale: str) -> str:
    method_value = str(method or "").strip().upper() or "GET"
    target_value = str(target or "").strip()
    item_type_value = str(item_type or "").strip().lower().replace("-", "_")
    auth_value = str(auth_hint or "").strip().lower()
    rationale_value = str(rationale or "").strip().lower()
    haystack = " ".join(
        value
        for value in [method_value.lower(), target_value.lower(), item_type_value, auth_value, rationale_value]
        if value
    )

    if item_type_value == "file" or "kdbx" in haystack or "/ftp/" in haystack or "file-upload" in haystack:
        return "file_handling"
    if any(token in haystack for token in ("swagger", "openapi", "api doc", "documented", "/api-docs", "/okx-api", "docs-v5")):
        return "api_documentation"
    if item_type_value in {"asset_distribution", "cdn_asset_host", "cdn_host", "download_host", "object_storage", "storage_bucket"} or any(
        token in haystack for token in ("asset host", "cdn host", "installer manifest", "object storage")
    ):
        return "dynamic_render"
    if any(token in haystack for token in ("forgot-password", "reset-password", "security-question", "account recovery", "password reset")):
        return "account_recovery"
    if any(token in haystack for token in ("change-password", "privileged")):
        return "privileged_write"
    if any(token in haystack for token in ("2fa", "totp", "otp", "token", "jwt", "session", "cookie", "workflow")):
        return "workflow_token"
    if any(token in haystack for token in ("object", "idor", "{id}", "/track-order/", "orderid")):
        return "object_reference"
    if method_value != "GET" and item_type_value == "api":
        return "privileged_write"
    if any(token in haystack for token in ("login", "register", "auth", "mfa")):
        return "auth_entry"
    if item_type_value == "page":
        return "dynamic_render"
    if not item_type_value and method_value == "GET" and target_value.startswith("GET /"):
        if not (
            target_value.startswith("GET /api")
            or re.match(r"GET /v\d", target_value)
            or target_value.startswith("GET /priapi")
            or target_value.startswith("GET /rest/")
            or re.match(r"GET /[^\s]+\.[^/\s]+$", target_value)
        ):
            return "dynamic_render"
    return ""


def _build_surface_target(payload: dict[str, object]) -> str:
    target = str(payload.get("target") or "").strip()
    if target:
        return _normalize_surface_target_placeholders(target)

    url_value = ""
    for key in ("url", "url/path", "path", "url_or_pattern", "urlOrPattern"):
        value = payload.get(key)
        if value is None:
            continue
        url_value = str(value).strip()
        if url_value:
            break
    if not url_value:
        return ""

    method = str(payload.get("method") or "GET").strip().upper() or "GET"
    return _normalize_surface_target_placeholders(f"{method} {url_value}")


def _surface_target_contains_placeholder(value: str) -> bool:
    if not value:
        return False
    return _SURFACE_PLACEHOLDER_PATTERN.search(value) is not None


def _normalize_surface_target_placeholders(value: str) -> str:
    normalized = str(value or "").strip()
    if not _surface_target_contains_placeholder(normalized):
        return normalized
    if len(_SURFACE_HTTP_METHOD_PATTERN.findall(normalized)) < 2:
        return normalized
    return _SURFACE_PLACEHOLDER_PATTERN.sub("...", normalized)


def _iter_runtime_text_fragments(payload):
    if isinstance(payload, str):
        yield payload
        return
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_runtime_text_fragments(value)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_runtime_text_fragments(item)


def _extract_surface_candidates_from_text(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    in_surface_section = False

    for raw_line in text.splitlines():
        stripped = _SURFACE_AGENT_PREFIX.sub("", raw_line.strip())
        if not stripped:
            continue
        if stripped == "#### Surface Candidates":
            in_surface_section = True
            continue
        if stripped.startswith("### ") or stripped.startswith("#### "):
            in_surface_section = False
            continue
        if not in_surface_section or not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        target = _build_surface_target(payload)
        source = str(payload.get("source") or payload.get("agent") or "").strip()
        rationale = str(payload.get("rationale") or payload.get("reason") or payload.get("notes") or "").strip()
        evidence_ref = str(payload.get("evidence_ref") or payload.get("evidence") or "").strip()
        status = str(payload.get("status") or "discovered").strip().lower().replace("-", "_")
        method = str(payload.get("method") or "GET").strip().upper() or "GET"
        item_type = str(payload.get("type") or "").strip()
        auth_hint = str(payload.get("auth") or "").strip()
        surface_type = _normalize_surface_type(payload.get("surface_type") or payload.get("category") or "")
        if surface_type not in _VALID_SURFACE_TYPES:
            surface_type = _infer_surface_type(method, target, item_type, auth_hint, rationale)
        if surface_type not in _VALID_SURFACE_TYPES:
            continue
        if status not in _VALID_SURFACE_STATUSES:
            status = "discovered"
        if not target or not source or not rationale:
            continue
        if _surface_target_contains_placeholder(target):
            continue

        records.append(
            {
                "surface_type": surface_type,
                "target": target,
                "source": source,
                "rationale": rationale,
                "evidence_ref": evidence_ref,
                "status": status,
            }
        )

    return records


def _canonicalize_surface_record(record: dict[str, str], context: dict[str, str] | None) -> dict[str, str]:
    normalized = _rewrite_artifact_value(record, context)
    if not isinstance(normalized, dict):
        return record
    canonical = dict(normalized)
    target = _build_surface_target(canonical)
    rationale = str(canonical.get("rationale") or canonical.get("reason") or canonical.get("notes") or "").strip()
    method = str(canonical.get("method") or "GET").strip().upper() or "GET"
    item_type = str(canonical.get("type") or "").strip()
    auth_hint = str(canonical.get("auth") or "").strip()
    surface_type = _normalize_surface_type(canonical.get("surface_type") or canonical.get("category") or "")
    if surface_type not in _VALID_SURFACE_TYPES:
        surface_type = _infer_surface_type(method, target, item_type, auth_hint, rationale)
    status = str(canonical.get("status") or "discovered").strip().lower().replace("-", "_")
    canonical["surface_type"] = surface_type
    canonical["status"] = status if status in _VALID_SURFACE_STATUSES else "discovered"
    canonical["target"] = target
    canonical["source"] = str(canonical.get("source") or canonical.get("agent") or "").strip()
    canonical["rationale"] = rationale
    canonical["evidence_ref"] = str(canonical.get("evidence_ref") or canonical.get("evidence") or "").strip()
    return canonical


def _dedupe_surface_jsonl(path: Path, context: dict[str, str] | None) -> None:
    if not path.exists():
        return

    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    trailing_newline = original.endswith("\n")
    rewritten_rows: list[str] = []
    seen_positions: dict[tuple[str, str], int] = {}
    changed = False

    for line in original.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            rewritten_line = _rewrite_loopback_text(line, context)
            if rewritten_line != line:
                changed = True
            rewritten_rows.append(rewritten_line)
            continue
        if not isinstance(payload, dict):
            rewritten_line = json.dumps(payload, separators=(",", ":"))
            if rewritten_line != line:
                changed = True
            rewritten_rows.append(rewritten_line)
            continue

        canonical = _canonicalize_surface_record(payload, context)
        if _surface_target_contains_placeholder(canonical.get("target", "")):
            changed = True
            continue
        rewritten_line = json.dumps(canonical, separators=(",", ":"))
        if rewritten_line != line:
            changed = True
        key = (canonical.get("surface_type", ""), canonical.get("target", ""))
        if all(key):
            if key in seen_positions:
                rewritten_rows[seen_positions[key]] = rewritten_line
                changed = True
            else:
                seen_positions[key] = len(rewritten_rows)
                rewritten_rows.append(rewritten_line)
        else:
            rewritten_rows.append(rewritten_line)

    rewritten = "\n".join(rewritten_rows)
    if rewritten and trailing_newline:
        rewritten += "\n"
    elif original and trailing_newline and not rewritten_rows:
        rewritten = ""

    if changed or rewritten != original:
        path.write_text(rewritten, encoding="utf-8")


def _backfill_surfaces_from_process_log(run: Run, engagement_dir: Path) -> None:
    process_log = process_log_path_for(run)
    if not process_log.exists():
        return

    context = _loopback_display_context(run)
    surfaces_path = engagement_dir / "surfaces.jsonl"
    existing_keys: set[tuple[str, str]] = set()
    if surfaces_path.exists():
        try:
            for line in surfaces_path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                if not isinstance(row, dict):
                    continue
                canonical = _canonicalize_surface_record(row, context)
                key = (canonical.get("surface_type", ""), canonical.get("target", ""))
                if all(key):
                    existing_keys.add(key)
        except json.JSONDecodeError:
            return

    appended_rows: list[dict[str, str]] = []
    try:
        for raw_line in process_log.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            for text in _iter_runtime_text_fragments(payload):
                if "#### Surface Candidates" not in text:
                    continue
                for record in _extract_surface_candidates_from_text(text):
                    canonical = _canonicalize_surface_record(record, context)
                    key = (canonical["surface_type"], canonical["target"])
                    if key in existing_keys:
                        continue
                    existing_keys.add(key)
                    appended_rows.append(canonical)
    except OSError:
        return

    if not appended_rows:
        return

    surfaces_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = surfaces_path.read_text(encoding="utf-8", errors="replace") if surfaces_path.exists() else ""
    with surfaces_path.open("a", encoding="utf-8") as handle:
        if existing_text and not existing_text.endswith("\n"):
            handle.write("\n")
        for row in appended_rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def normalize_active_scope(run: Run) -> None:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return

    context = _loopback_display_context(run)
    scope = _normalize_scope_file(engagement_dir / "scope.json", run=run)
    _normalize_completion_artifacts(engagement_dir, scope)
    _backfill_surfaces_from_process_log(run, engagement_dir)
    _dedupe_surface_jsonl(engagement_dir / "surfaces.jsonl", context)
    _normalize_jsonl_artifact(
        engagement_dir / "scans" / "katana_output.jsonl",
        context,
        redact_headers=True,
        preserve_malformed=not _should_persist_loopback_rewrite(run),
    )
    if context is None:
        return

    _normalize_text_artifact(engagement_dir / "log.md", context)
    _normalize_text_artifact(engagement_dir / "findings.md", context)
    _normalize_text_artifact(engagement_dir / "report.md", context)
    if _should_persist_loopback_rewrite(run):
        _normalize_cases_db(engagement_dir / "cases.db", context)


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
    payload["ended_at"] = str(payload.get("ended_at") or run.updated_at)
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clear_run_terminal_reason(run: Run) -> None:
    metadata_path = metadata_path_for(run)
    if not metadata_path.exists():
        return
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    payload.pop("stop_reason_code", None)
    payload.pop("stop_reason_text", None)
    payload.pop("ended_at", None)
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
    normalize_active_scope(run)
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
        normalized_auth = _normalize_auth_payload(project.auth_json)
        (seed_root_for(run) / "auth.json").write_text(normalized_auth + "\n", encoding="utf-8")
    elif (seed_root_for(run) / "auth.json").exists():
        (seed_root_for(run) / "auth.json").unlink()

    if project.env_json.strip():
        (seed_root_for(run) / "env.json").write_text(project.env_json + "\n", encoding="utf-8")
    elif (seed_root_for(run) / "env.json").exists():
        (seed_root_for(run) / "env.json").unlink()

    metadata = {
        "id": run.id,
        "project_id": project.id,
        "project_slug": project.slug,
        "run_id": run.id,
        "target": run.target,
        "status": run.status,
        "engagement_root": run.engagement_root,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
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


def _read_run_metadata(run: Run) -> dict[str, object]:
    metadata_path = metadata_path_for(run)
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _update_run_metadata(run: Run, **fields: object) -> None:
    payload = _read_run_metadata(run)
    payload.update(fields)
    metadata_path_for(run).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _current_auto_resume_count(run: Run) -> int:
    value = _read_run_metadata(run).get("auto_resume_count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _current_auto_resume_progress(run: Run) -> int | None:
    value = _read_run_metadata(run).get("auto_resume_progress")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _set_auto_resume_count(run: Run, count: int) -> None:
    _update_run_metadata(run, auto_resume_count=max(0, int(count)))


def _current_queue_resolution_count(run: Run) -> int | None:
    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return None
    _, total_cases, pending_cases, processing_cases = _load_running_queue_state(engagement_dir)
    if total_cases <= 0:
        return None
    return max(0, total_cases - pending_cases - processing_cases)


def _set_auto_resume_progress(run: Run, resolved_count: int | None) -> None:
    if resolved_count is None:
        return
    _update_run_metadata(run, auto_resume_progress=max(0, int(resolved_count)))


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
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_status(container_name: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return _CONTAINER_STATUS_LOOKUP_UNAVAILABLE
    if result.returncode != 0:
        return None
    status = result.stdout.strip()
    return status or None


def _container_exit_code(container_name: str) -> int | None:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _looks_like_runtime_process(command: str, *, container_name: str | None) -> bool:
    normalized = command.strip()
    if not normalized:
        return False

    if " docker logs " in f" {normalized} ":
        return False

    runtime_markers = (
        " opencode run --format json /autoengage ",
        " opencode run --format json /resume ",
        " docker run ",
    )
    if any(marker in f" {normalized} " for marker in runtime_markers):
        if container_name and container_name in normalized and " docker run " in f" {normalized} ":
            return True
        if " opencode run --format json /" in f" {normalized} ":
            return True

    return False


def _runtime_log_follower_pids(container_name: str | None) -> list[int]:
    if not container_name:
        return []

    try:
        output = subprocess.check_output(["ps", "eww", "-axo", "pid=,command="], text=True)
    except (subprocess.SubprocessError, OSError):
        return []

    follower_pids: list[int] = []
    for line in output.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        if container_name not in normalized:
            continue
        if " docker logs " not in f" {normalized} ":
            continue
        pid_text, _, _ = normalized.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if _pid_alive(pid):
            follower_pids.append(pid)
    return follower_pids


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
        if status == _CONTAINER_STATUS_LOOKUP_UNAVAILABLE:
            return RUNTIME_PID_LOOKUP_UNAVAILABLE
        if status in {"running", "restarting"}:
            return RUNTIME_PID_CONTAINER
        if status == "created":
            try:
                launcher_pid = int(payload.get("launcher_pid"))
            except (ValueError, TypeError):
                launcher_pid = None
            if launcher_pid == os.getpid():
                return RUNTIME_PID_CONTAINER
            return None
        if status is not None:
            return None

    try:
        output = subprocess.check_output(["ps", "eww", "-axo", "pid=,command="], text=True)
    except (subprocess.SubprocessError, OSError):
        return RUNTIME_PID_LOOKUP_UNAVAILABLE

    needle = f"ORCHESTRATOR_RUN_ID={run.id}"
    for line in output.splitlines():
        if needle not in line:
            continue
        normalized = line.strip()
        if not _looks_like_runtime_process(normalized, container_name=container_name):
            continue
        pid_text, _, _ = normalized.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if _pid_alive(pid):
            process_metadata_path_for(run).write_text(
                json.dumps({"pid": pid, "run_id": run.id, "command": normalized}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return pid
    return None


def stop_run_runtime(run: Run) -> None:
    container_name = _container_name_from_metadata(run)
    if not container_name:
        container_name = runtime_container_name(run)
    if container_name:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        for follower_pid in _runtime_log_follower_pids(container_name):
            try:
                os.kill(follower_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    pid = locate_runtime_pid(run)
    if isinstance(pid, int) and pid > 0:
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


def _drain_runtime_log_follower(log_follower: subprocess.Popen[bytes] | None, *, timeout: int = 5) -> None:
    if log_follower is None or log_follower.poll() is not None:
        return
    try:
        log_follower.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return


def _close_log_streams(log_follower: subprocess.Popen[bytes] | None, log_handle) -> None:
    if log_follower is not None and log_follower.poll() is None:
        log_follower.terminate()
        try:
            log_follower.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log_follower.kill()
    log_handle.close()


def _runtime_log_follow_command(run: Run) -> list[str]:
    command = ["docker", "logs", "-f"]
    process_log = process_log_path_for(run)
    if process_log.exists():
        try:
            has_history = process_log.stat().st_size > 0
        except OSError:
            has_history = False
        if has_history:
            latest_activity = _latest_process_log_activity_at(process_log)
            if latest_activity is not None:
                # `docker logs --since` is inclusive. Advancing by 1 ms avoids
                # replaying the last captured line each time the follower is
                # restarted, which otherwise duplicates structured runtime
                # events in process.log.
                since_at = datetime.fromtimestamp(latest_activity, UTC) + timedelta(milliseconds=1)
                since_value = since_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                command.extend(["--since", since_value])
    command.append(runtime_container_name(run))
    return command



def _spawn_runtime_log_follower(run: Run, log_handle) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        _runtime_log_follow_command(run),
        cwd=str(run.engagement_root),
        env=os.environ.copy(),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def _ensure_runtime_log_follower(run: Run, log_follower: subprocess.Popen[bytes] | None, log_handle) -> subprocess.Popen[bytes] | None:
    if log_follower is None:
        return _spawn_runtime_log_follower(run, log_handle)
    if log_follower.poll() is None:
        return log_follower
    return _spawn_runtime_log_follower(run, log_handle)


def _runtime_command_text(run: Run, *, resume: bool = False) -> str:
    if resume:
        return "/resume"
    return f"/autoengage {_rewrite_runtime_target(run.target)}"


def _launch_runtime_container(
    project: Project,
    run: Run,
    user: User,
    *,
    command_text: str,
    log_handle,
) -> subprocess.Popen[bytes]:
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

    docker_command = [
        "docker",
        "run",
        "-d",
        "--init",
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
        command_text,
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
    return _spawn_runtime_log_follower(run, log_handle)


def _maybe_auto_resume_run(
    project: Project,
    run: Run,
    user: User,
    *,
    phase: str,
    reason_code: str,
    reason_text: str,
) -> bool:
    if reason_code not in _AUTO_RESUME_REASON_CODES:
        return False

    engagement_dir = _active_engagement_dir(run)
    if engagement_dir is None:
        return False

    phase_name = _canonical_phase_name(phase)
    scope = _normalize_scope_file(engagement_dir / "scope.json", run=run) or {}
    scope_phase = _canonical_phase_name(scope.get("current_phase")) if isinstance(scope, dict) else "unknown"
    if phase_name in {"report", "complete"} or scope_phase in {"report", "complete"}:
        return False

    attempt = _current_auto_resume_count(run)
    resolved_count = _current_queue_resolution_count(run)
    last_resolved_count = _current_auto_resume_progress(run)
    if (
        resolved_count is not None
        and last_resolved_count is not None
        and resolved_count > last_resolved_count
    ):
        attempt = 0

    if attempt >= _AUTO_RESUME_LIMIT:
        return False

    recovery_note = ""
    if phase_name == "consume_test" or scope_phase == "consume_test":
        recovered_cases, recovered_agents = _recover_orphaned_processing_cases(run, engagement_dir)
        if recovered_cases > 0:
            agents_text = ", ".join(sorted(recovered_agents))
            recovery_note = (
                f" Re-queued {recovered_cases} orphaned processing case(s)"
                + (f" from {agents_text}" if agents_text else "")
                + " before /resume."
            )

    next_attempt = attempt + 1
    _set_auto_resume_count(run, next_attempt)
    _set_auto_resume_progress(run, resolved_count)
    _append_runtime_event(
        run,
        "run.resumed",
        phase,
        f"Relaunching /resume after {reason_code} ({next_attempt}/{_AUTO_RESUME_LIMIT}): {reason_text}{recovery_note}",
    )
    resumed = db.get_run_by_id(run.id) or run
    if resumed.status != "running":
        resumed = db.update_run_status(run.id, "running")
    _clear_run_terminal_reason(resumed)
    log_handle = open(process_log_path_for(run), "ab")
    log_follower = _launch_runtime_container(
        project,
        resumed,
        user,
        command_text=_runtime_command_text(resumed, resume=True),
        log_handle=log_handle,
    )
    _start_container_supervisor(
        resumed,
        project,
        user,
        log_follower=log_follower,
        log_handle=log_handle,
        replace_existing=True,
    )
    return True


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
    normalize_active_scope(run)
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


def _start_container_supervisor(
    run: Run,
    project: Project,
    user: User,
    *,
    log_follower: subprocess.Popen[bytes] | None = None,
    log_handle=None,
    replace_existing: bool = False,
) -> bool:
    supervisor_token = object()
    with _ACTIVE_CONTAINER_SUPERVISORS_LOCK:
        if run.id in _ACTIVE_CONTAINER_SUPERVISORS and not replace_existing:
            return False
        _ACTIVE_CONTAINER_SUPERVISORS[run.id] = supervisor_token

    created_log_handle = False
    try:
        if log_handle is None:
            process_log_path_for(run).parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(process_log_path_for(run), "ab")
            created_log_handle = True

        def _runner(_run: Run) -> None:
            try:
                _supervise_container(
                    run,
                    project,
                    user,
                    runtime_container_name(run),
                    log_follower,
                    log_handle,
                )
            finally:
                with _ACTIVE_CONTAINER_SUPERVISORS_LOCK:
                    if _ACTIVE_CONTAINER_SUPERVISORS.get(run.id) is supervisor_token:
                        _ACTIVE_CONTAINER_SUPERVISORS.pop(run.id, None)

        Thread(target=_runner, args=(run,), daemon=True).start()
        return True
    except Exception:
        if created_log_handle and log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
        with _ACTIVE_CONTAINER_SUPERVISORS_LOCK:
            if _ACTIVE_CONTAINER_SUPERVISORS.get(run.id) is supervisor_token:
                _ACTIVE_CONTAINER_SUPERVISORS.pop(run.id, None)
        raise


def _supervise_container(
    run: Run,
    project: Project,
    user: User,
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
            log_follower = _ensure_runtime_log_follower(run, log_follower, log_handle)
            phase, summary = _heartbeat_context(run)
            _append_runtime_event(run, "run.heartbeat", phase, summary)

            live_stall = _running_container_stall_reason(run)
            if live_stall is not None:
                phase, reason_code, reason_text = live_stall
                stop_run_runtime(run)
                refreshed = db.get_run_by_id(run.id) or run
                if not _maybe_auto_resume_run(
                    project,
                    refreshed,
                    user,
                    phase=phase,
                    reason_code=reason_code,
                    reason_text=reason_text,
                ):
                    _append_runtime_event(refreshed, "run.failed", phase, reason_text)
                    terminal = db.update_run_status(run.id, "failed")
                    _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)
                break

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
            _drain_runtime_log_follower(log_follower)
            exit_code = _container_exit_code(container_name)
            phase, _ = _heartbeat_context(run)
            normalize_active_scope(run)
            completion_ok, completion_reason = engagement_completion_state(run)
            init_only_exit = _init_only_exit(run)
            succeeded = exit_code == 0 and not init_only_exit and completion_ok
            reason_code, reason_text, summary = _terminal_reason(
                succeeded=succeeded,
                return_code=exit_code,
                completion_reason=completion_reason,
                init_only_exit=init_only_exit,
            )
            if not succeeded and _maybe_auto_resume_run(
                project,
                run,
                user,
                phase=phase,
                reason_code=reason_code,
                reason_text=reason_text,
            ):
                _close_log_streams(log_follower, log_handle)
                return
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
            _drain_runtime_log_follower(log_follower)
            phase, _ = _heartbeat_context(run)
            succeeded, reason_code, reason_text, summary = _terminal_reason_from_artifacts(run)
            if not succeeded and _maybe_auto_resume_run(
                project,
                run,
                user,
                phase=phase,
                reason_code=reason_code,
                reason_text=reason_text,
            ):
                _close_log_streams(log_follower, log_handle)
                return
            _append_runtime_event(run, "run.completed" if succeeded else "run.failed", phase, summary)
            terminal = db.update_run_status(run.id, "completed" if succeeded else "failed")
            _write_run_terminal_reason(terminal, reason_code=reason_code, reason_text=reason_text)
            break
        time.sleep(heartbeat_interval)

    _close_log_streams(log_follower, log_handle)


def start_run_runtime(project: Project, run: Run, user: User) -> Run:
    prepare_run_runtime(project, run)
    process_log_path_for(run).parent.mkdir(parents=True, exist_ok=True)
    _set_auto_resume_count(run, 0)
    _update_run_metadata(run, auto_resume_progress=None)
    log_handle = open(process_log_path_for(run), "ab")

    try:
        log_follower = _launch_runtime_container(
            project,
            run,
            user,
            command_text=_runtime_command_text(run),
            log_handle=log_handle,
        )
    except Exception as exc:
        log_handle.write(f"launcher failed: {exc!r}\n".encode("utf-8"))
        log_handle.close()
        return db.update_run_status(run.id, "failed")

    running = db.update_run_status(run.id, "running")
    _clear_run_terminal_reason(running)
    _append_runtime_event(running, "run.started", "initializing", "Runtime launched; waiting for agent activity.")
    _start_container_supervisor(
        running,
        project,
        user,
        log_follower=log_follower,
        log_handle=log_handle,
    )
    return running
