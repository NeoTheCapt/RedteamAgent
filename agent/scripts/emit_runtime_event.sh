#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<USAGE
usage: emit_runtime_event.sh <event_type> <phase> <task_name> <agent_name> <summary>
                             [--kind <kind>] [--level <level>]
                             [--payload-json <json>]
USAGE
    exit 2
}

[[ $# -lt 5 ]] && usage

EVENT_TYPE="$1"; PHASE="$2"; TASK_NAME="$3"; AGENT_NAME="$4"; SUMMARY="$5"
shift 5

KIND=""
LEVEL="info"
PAYLOAD_JSON="{}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kind)         KIND="$2"; shift 2 ;;
        --level)        LEVEL="$2"; shift 2 ;;
        --payload-json) PAYLOAD_JSON="$2"; shift 2 ;;
        *) echo "emit_runtime_event.sh: unknown flag: $1" >&2; usage ;;
    esac
done

if [[ -z "${ORCHESTRATOR_BASE_URL:-}" \
   || -z "${ORCHESTRATOR_TOKEN:-}" \
   || -z "${ORCHESTRATOR_PROJECT_ID:-}" \
   || -z "${ORCHESTRATOR_RUN_ID:-}" ]]; then
    exit 0
fi

payload="$(python3 - <<'PY' "$EVENT_TYPE" "$PHASE" "$TASK_NAME" "$AGENT_NAME" "$SUMMARY" "$KIND" "$LEVEL" "$PAYLOAD_JSON"
import json, sys
event_type, phase, task_name, agent_name, summary, kind, level, payload_json = sys.argv[1:]
body = {
    "event_type": event_type,
    "phase": phase,
    "task_name": task_name,
    "agent_name": agent_name,
    "summary": summary,
    "kind": kind or "legacy",
    "level": level,
}
try:
    body["payload"] = json.loads(payload_json) if payload_json else {}
except json.JSONDecodeError:
    body["payload"] = {}
print(json.dumps(body, ensure_ascii=True))
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
        "${ORCHESTRATOR_BASE_URL%/}/projects/${ORCHESTRATOR_PROJECT_ID}/runs/${ORCHESTRATOR_RUN_ID}/events" \
        >/dev/null || {
            printf 'warning: failed to emit runtime event %s\n' "$EVENT_TYPE" >&2
            exit 0
        }
) >/dev/null 2>&1 &
