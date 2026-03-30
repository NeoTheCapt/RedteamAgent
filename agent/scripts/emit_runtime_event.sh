#!/usr/bin/env bash
set -euo pipefail

EVENT_TYPE="${1:?usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>}"
PHASE="${2:?usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>}"
TASK_NAME="${3:?usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>}"
AGENT_NAME="${4:?usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>}"
SUMMARY="${5:?usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>}"

if [[ -z "${ORCHESTRATOR_BASE_URL:-}" || -z "${ORCHESTRATOR_TOKEN:-}" || -z "${ORCHESTRATOR_PROJECT_ID:-}" || -z "${ORCHESTRATOR_RUN_ID:-}" ]]; then
    exit 0
fi

payload="$(python3 - <<'PY' "$EVENT_TYPE" "$PHASE" "$TASK_NAME" "$AGENT_NAME" "$SUMMARY"
import json
import sys

event_type, phase, task_name, agent_name, summary = sys.argv[1:]
print(json.dumps({
    "event_type": event_type,
    "phase": phase,
    "task_name": task_name,
    "agent_name": agent_name,
    "summary": summary,
}, ensure_ascii=True))
PY
)"

(
  curl -fsS \
    --connect-timeout 1 \
    --max-time 2 \
    -H "Authorization: Bearer ${ORCHESTRATOR_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    --data "$payload" \
    "${ORCHESTRATOR_BASE_URL%/}/projects/${ORCHESTRATOR_PROJECT_ID}/runs/${ORCHESTRATOR_RUN_ID}/events" >/dev/null || {
      printf 'warning: failed to emit runtime event %s\n' "$EVENT_TYPE" >&2
      exit 0
    }
) >/dev/null 2>&1 &
