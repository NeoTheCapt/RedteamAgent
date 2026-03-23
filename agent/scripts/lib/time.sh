#!/usr/bin/env bash

engagement_now_utc() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

engagement_header_date_today() {
    date +%Y-%m-%d
}

engagement_header_date_from_utc() {
    local iso_utc="${1:?utc timestamp required}"

    python3 - <<'PY' "$iso_utc"
from datetime import datetime, timezone
import sys

value = sys.argv[1]
dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
print(dt.astimezone().strftime("%Y-%m-%d"))
PY
}
