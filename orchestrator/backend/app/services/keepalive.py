"""Keepalive: recreate runs automatically for configured long-lived targets.

Motivation: the scheduled auditor cycle runs every 30 minutes and its prep
phase (`run_cycle_prep.sh::recover_abnormal_runs`) is what normally replaces
failed/stopped runs. That means a run that fails mid-cycle sits in `failed`
state for up to 30 minutes before it's replaced. For "observation" targets
(local Juice Shop, OKX) this leaves the operator staring at a dead run.

This background task fills the gap: every `keepalive_interval_seconds` it
checks each configured target on the configured project. If the latest run
for that target is in a terminal status (failed/stopped/cancelled/etc.)
AND older than `keepalive_grace_seconds`, it creates a fresh replacement.
It never deletes the terminal run — the operator can still inspect the
failure.

Disabled by default. Turn on via env:

    REDTEAM_ORCHESTRATOR_KEEPALIVE_PROJECT_ID=<id>
    REDTEAM_ORCHESTRATOR_KEEPALIVE_TARGETS=<comma-separated target urls>
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .. import db
from ..config import settings
from ..models.run import Run
from .runs import create_run_for_project

logger = logging.getLogger(__name__)

# Run.status values that indicate the run is terminally done and should be
# replaced by a fresh one. `completed` is included for long-lived targets
# where a cycle completing normally still warrants restart for the next
# observation window.
TERMINAL_STATUSES = {
    "failed",
    "failure",
    "error",
    "errored",
    "stopped",
    "cancelled",
    "canceled",
    "timeout",
    "completed",
}

ACTIVE_STATUSES = {"queued", "running"}


def _targets_list() -> list[str]:
    raw = settings.keepalive_targets or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _normalize_target(target: str) -> str:
    return (target or "").strip().rstrip("/")


def _latest_run_for_target(runs: list[Run], target: str) -> Run | None:
    target_norm = _normalize_target(target)
    matches = [r for r in runs if _normalize_target(r.target) == target_norm]
    if not matches:
        return None
    return max(matches, key=lambda r: r.id)


def _parse_run_time(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _age_seconds(run: Run) -> float:
    # Prefer updated_at (last orchestrator-observed state change) over
    # created_at — a long-running run that just failed should be replaced
    # immediately, not wait grace-seconds past its creation time.
    ts = _parse_run_time(run.updated_at) or _parse_run_time(run.created_at)
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - ts).total_seconds()


def _keepalive_user():
    """Resolve the User instance that owns the keepalive project."""
    project = db.get_project_by_id(settings.keepalive_project_id)
    if project is None:
        return None
    return db.get_user_by_id(project.user_id)


def _replace_if_stale(project_id: int, targets: list[str]) -> int:
    """Walk targets once; return number of runs created."""
    created = 0
    user = _keepalive_user()
    if user is None:
        logger.warning(
            "keepalive: project %s or its owner not found; disabling sweep",
            project_id,
        )
        return 0

    runs = db.list_runs_for_project(project_id)

    for target in targets:
        latest = _latest_run_for_target(runs, target)
        should_create = False
        reason = ""

        if latest is None:
            should_create = True
            reason = "no run exists"
        elif latest.status in TERMINAL_STATUSES:
            # Only replace once grace has elapsed, to avoid flapping with
            # an agent cycle that briefly marks the run completed during
            # a clean handoff.
            age = _age_seconds(latest)
            if age >= settings.keepalive_grace_seconds:
                should_create = True
                reason = f"latest run #{latest.id} status={latest.status} age={age:.0f}s"
            else:
                logger.debug(
                    "keepalive: target=%s latest=%d status=%s age=%.0fs (<grace %ds); skip",
                    target, latest.id, latest.status, age, settings.keepalive_grace_seconds,
                )
        elif latest.status in ACTIVE_STATUSES:
            continue
        else:
            logger.debug(
                "keepalive: target=%s latest=%d status=%s (unknown); skip",
                target, latest.id, latest.status,
            )

        if should_create:
            try:
                new_run = create_run_for_project(project_id, user, target)
                logger.info(
                    "keepalive: created run #%d for target=%s reason=%s",
                    new_run.id, target, reason,
                )
                created += 1
            except Exception:
                logger.exception(
                    "keepalive: failed to create run for target=%s reason=%s",
                    target, reason,
                )

    return created


async def keepalive_loop() -> None:
    """Long-running background task. Noops if keepalive isn't configured."""
    project_id = settings.keepalive_project_id
    targets = _targets_list()
    interval = max(int(settings.keepalive_interval_seconds or 0), 10)

    if project_id <= 0 or not targets:
        logger.info(
            "keepalive: disabled (project_id=%s targets=%s)", project_id, targets,
        )
        return

    logger.info(
        "keepalive: started (project_id=%d targets=%s interval=%ds grace=%ds)",
        project_id, targets, interval, settings.keepalive_grace_seconds,
    )

    while True:
        try:
            # create_run_for_project calls prepare_run_runtime which does
            # blocking filesystem work; run it off the event loop.
            await asyncio.to_thread(_replace_if_stale, project_id, targets)
        except asyncio.CancelledError:
            logger.info("keepalive: cancelled; shutting down sweep loop")
            raise
        except Exception:
            logger.exception("keepalive: sweep iteration failed")
        await asyncio.sleep(interval)
