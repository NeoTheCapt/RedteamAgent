#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
SUBCOMMAND="${1:-}"
shift || true

transform_prompt() {
  python3 - <<'PY' "$1"
import sys
text = sys.argv[1]
text = text.replace('Use the workspace skill `scan-optimizer-loop`.\n\n', '', 1)
text = text.replace('OpenClaw', 'Hermes')
print(text)
PY
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  python3 - "$timeout_seconds" "$@" <<'PY'
import subprocess, sys

timeout = int(sys.argv[1])
cmd = sys.argv[2:]
try:
    result = subprocess.run(cmd, timeout=timeout)
    sys.exit(result.returncode)
except subprocess.TimeoutExpired:
    print(f"hermes compat timeout after {timeout}s", file=sys.stderr)
    sys.exit(124)
PY
}

run_hermes_cli() {
  local timeout_seconds="$1"
  shift
  if command -v hermes >/dev/null 2>&1; then
    run_with_timeout "$timeout_seconds" hermes "$@"
    return $?
  fi

  if [[ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]]; then
    run_with_timeout "$timeout_seconds" "$HOME/.hermes/hermes-agent/venv/bin/python" -m hermes_cli.main "$@"
    return $?
  fi

  echo "failed to locate hermes CLI" >&2
  return 127
}

case "$SUBCOMMAND" in
  agent)
    session_id=""
    message=""
    timeout_seconds="${OPENCLAW_TIMEOUT_SECONDS:-1800}"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --session-id)
          session_id="${2:-}"
          shift 2
          ;;
        --message)
          message="${2:-}"
          shift 2
          ;;
        --timeout)
          timeout_seconds="${2:-$timeout_seconds}"
          shift 2
          ;;
        *)
          echo "unsupported compat agent arg: $1" >&2
          exit 2
          ;;
      esac
    done

    if [[ -z "$message" ]]; then
      echo "compat agent mode requires --message" >&2
      exit 2
    fi

    transformed_message="$(transform_prompt "$message")"
    # Historical accident: controllers export OPENCLAW_SKILL, but this shim
    # originally only read HERMES_SKILL. That mismatch caused the auditor's
    # toolset dispatch below to silently fall through to the scan-optimizer
    # branch (verified in cycle 20260422T080126Z — no browser was loaded
    # despite OPENCLAW_SKILL=redteam-auditor-hermes). Fall back to
    # OPENCLAW_SKILL so either name works.
    skill_name="${HERMES_SKILL:-${OPENCLAW_SKILL:-scan-optimizer-hermes}}"
    # Default toolsets depend on the skill: the redteam-auditor cycle needs
    # `browser`+`web`+`vision` so the orch_ui oracle can actually render the
    # Dashboard / Progress pages and catch UI gaps that pure-API probes
    # (orch_api/orch_log/orch_feature) can't see. Can still override via
    # HERMES_TOOLSETS if an operator wants a narrower session.
    case "$skill_name" in
        redteam-auditor-hermes)
            default_toolsets="terminal,file,skills,browser,web,vision"
            ;;
        *)
            default_toolsets="terminal,file,skills"
            ;;
    esac
    toolsets="${HERMES_TOOLSETS:-$default_toolsets}"
    source_tag="${HERMES_SOURCE_TAG:-scan-optimizer-compat}"

    cd "$REPO_ROOT"
    run_hermes_cli "$timeout_seconds" -s "$skill_name" chat -q "$transformed_message" -Q -t "$toolsets" --source "$source_tag"
    ;;

  message)
    if [[ "${1:-}" != "send" ]]; then
      echo "unsupported compat message subcommand: ${1:-}" >&2
      exit 2
    fi
    shift
    channel=""
    target=""
    body=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --channel) channel="${2:-}"; shift 2 ;;
        --target)  target="${2:-}"; shift 2 ;;
        --message) body="${2:-}"; shift 2 ;;
        *)         echo "unsupported compat message-send arg: $1" >&2; exit 2 ;;
      esac
    done
    if [[ -z "$channel" || -z "$target" || -z "$body" ]]; then
      echo "compat message send requires --channel, --target and --message" >&2
      exit 2
    fi
    python_bin="${HERMES_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python}"
    if [[ ! -x "$python_bin" ]]; then
      python_bin="$(command -v python3)"
    fi
    "$python_bin" "$ROOT_DIR/scripts/hermes_send_message.py" \
      --channel "$channel" --target "$target" --message "$body"
    ;;

  *)
    echo "unsupported compat subcommand: ${SUBCOMMAND:-<none>}" >&2
    exit 2
    ;;
esac
