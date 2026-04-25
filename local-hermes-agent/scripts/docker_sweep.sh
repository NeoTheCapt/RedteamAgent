#!/usr/bin/env bash
# Daily Docker garbage sweep. Belt-and-braces complement to the per-cycle
# prune in run_cycle.sh: catches containers/caches that the per-cycle path
# doesn't touch, and runs even on days the auditor doesn't fire.
#
# What it prunes:
#   - dangling images (same as per-cycle)
#   - stopped containers whose exit is older than 24h
#   - builder cache entries older than 168h (7 days)
#
# What it does NOT touch:
#   - any image with at least one tag (keeps redteam-allinone, kali-redteam,
#     etc. even if unused for a while — operator decides when those go)
#   - running/queued containers
#   - volumes / networks
#
# Runs via launchd (`com.neothecapt.docker-sweep.plist`), once a day at 03:00.
# Safe to run manually any time.

set -u

LOG_DIR="$(cd "$(dirname "$0")/.." && pwd)/logs"
LOG="$LOG_DIR/docker-sweep.log"
mkdir -p "$LOG_DIR"

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

{
  echo "===== $(ts) docker-sweep start ====="

  if ! command -v docker >/dev/null 2>&1; then
    echo "$(ts) docker CLI missing; skipping"
    exit 0
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "$(ts) docker daemon unreachable (OrbStack stopped?); skipping"
    exit 0
  fi

  echo "$(ts) before:"
  docker system df | sed 's/^/  /'

  echo "$(ts) image prune (dangling only):"
  docker image prune -f 2>&1 | sed 's/^/  /' || true

  echo "$(ts) container prune (stopped >24h):"
  docker container prune -f --filter "until=24h" 2>&1 | sed 's/^/  /' || true

  echo "$(ts) builder prune (cache >7d):"
  docker builder prune -a -f --filter "until=168h" 2>&1 | sed 's/^/  /' || true

  echo "$(ts) after:"
  docker system df | sed 's/^/  /'

  echo "===== $(ts) docker-sweep done ====="
  echo
} >> "$LOG" 2>&1
