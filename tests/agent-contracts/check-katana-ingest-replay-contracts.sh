#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "status": "in_progress",
  "start_time": "2026-03-28T00:00:00Z",
  "phases_completed": [],
  "current_phase": "recon"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys

payload = {
    "timestamp": "2026-03-28T00:00:00Z",
    "request": {
        "method": "GET",
        "endpoint": "http://host.docker.internal:8000"
    },
    "response": {
        "status_code": 200,
        "headers": {
            "Content-Type": "text/html; charset=UTF-8"
        },
        "xhr_requests": [
            {
                "method": "GET",
                "endpoint": "http://host.docker.internal:8000/rest/admin/application-version",
                "headers": {
                    "Accept": "application/json"
                }
            },
            {
                "method": "POST",
                "endpoint": "http://host.docker.internal:8000/socket.io/?EIO=4&transport=polling&t=abc",
                "headers": {
                    "Content-Type": "text/plain;charset=UTF-8"
                }
            }
        ]
    }
}

# Intentionally omit trailing newline to mimic Katana's observed output.
Path(sys.argv[1]).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
PY

KATANA_INGEST_SKIP_START=1 KATANA_INGEST_ONESHOT=1 "$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null

total_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$total_cases" -ge 3 ]] || {
  echo "expected katana replay to ingest top-level + xhr requests, got $total_cases cases" >&2
  exit 1
}

sqlite3 "$ENG_DIR/cases.db" 'select source from cases order by source;' | grep -qx 'katana'
sqlite3 "$ENG_DIR/cases.db" 'select source from cases order by source;' | grep -qx 'katana-xhr'
sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -q '/rest/admin/application-version'
sqlite3 "$ENG_DIR/cases.db" 'select url from cases order by url;' | grep -q '/socket.io/'
root_path="$(sqlite3 "$ENG_DIR/cases.db" "select url_path from cases where source='katana' order by id limit 1;")"
[[ "$root_path" == "/" ]] || {
  echo "expected top-level katana request to normalize to /, got: $root_path" >&2
  exit 1
}

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys

payload = {
    "timestamp": "2026-03-28T00:01:00Z",
    "request": {
        "method": "GET",
        "endpoint": "http://host.docker.internal:8000/recoverable"
    },
    "error": "hybrid: response is nil"
}
Path(sys.argv[1]).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
PY
sqlite3 "$ENG_DIR/cases.db" 'delete from cases;'
KATANA_INGEST_SKIP_START=1 KATANA_INGEST_ONESHOT=1 "$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null
recoverable_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$recoverable_cases" -ge 1 ]] || {
  echo "expected recoverable katana error rows to be ingested, got $recoverable_cases cases" >&2
  exit 1
}
sqlite3 "$ENG_DIR/cases.db" 'select url from cases;' | grep -q '/recoverable'

python3 - <<'PY' "$ENG_DIR/scans/katana_output.jsonl"
from pathlib import Path
import json
import sys

rows = [
    {
        "timestamp": "2026-03-28T00:02:00Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/rest/admin/application-configuration",
            "source": "http://host.docker.internal:8000/"
        },
        "response": {
            "status_code": 200,
            "headers": {
                "Content-Type": "application/json; charset=UTF-8"
            }
        }
    },
    {
        "timestamp": "2026-03-28T00:02:01Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/rest/admin/%5C%22/",
            "tag": "a",
            "attribute": "href",
            "source": "http://host.docker.internal:8000/rest/admin/application-configuration"
        },
        "response": {
            "status_code": 500,
            "headers": {
                "Content-Type": "text/html; charset=UTF-8"
            }
        }
    },
    {
        "timestamp": "2026-03-28T00:02:02Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/assets/public/images/w",
            "tag": "html",
            "attribute": "regex",
            "source": "http://host.docker.internal:8000/assets/public/images/JuiceShop_Logo.png"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:03Z",
        "request": {
            "method": "GET",
            "endpoint": "https://www.okx.com/*/kyc-verify$",
            "tag": "file",
            "attribute": "robotstxt",
            "source": "https://www.okx.com/robots.txt"
        },
        "error": "hybrid: response is nil"
    },
    {
        "timestamp": "2026-03-28T00:02:03.100Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/%5C/index.html",
            "tag": "html",
            "attribute": "regex",
            "source": "http://host.docker.internal:8000/chunk-LHKS7QUN.js"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:03.200Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/assets/public/images/chunk-24EZLZ4I.js",
            "tag": "link",
            "attribute": "href",
            "source": "http://host.docker.internal:8000/assets/public/images/"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:03.300Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/assets/public/images/assets/public/main.js",
            "tag": "script",
            "attribute": "src",
            "source": "http://host.docker.internal:8000/assets/public/images/assets/public/favicon_js.ico"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:03.400Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/assets/i18n/assets/public/polyfills.js",
            "tag": "script",
            "attribute": "src",
            "source": "http://host.docker.internal:8000/assets/i18n/assets/public/favicon_js.ico"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:04Z",
        "request": {
            "method": "GET",
            "endpoint": "https://www.okx.com/cdn/assets/okfe/util/monitor/2.6.149/scripts/lib/",
            "tag": "html",
            "attribute": "regex",
            "source": "https://www.okx.com/cdn/assets/okfe/util/monitor/2.6.149/index.js"
        },
        "error": "hybrid: response is nil"
    },
    {
        "timestamp": "2026-03-28T00:02:05Z",
        "request": {
            "method": "GET",
            "endpoint": "https://www.okx.com/cdn/assets/okfe/okt/polyfill-automatic/Bun/",
            "tag": "html",
            "attribute": "regex",
            "source": "https://www.okx.com/cdn/assets/okfe/okt/polyfill-automatic/f220424697ac3c8ba96a.wasm.br"
        },
        "error": "hybrid: response is nil"
    },
    {
        "timestamp": "2026-03-28T00:02:06Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/juice-shop/node_modules/express/lib/router/index.js",
            "tag": "html",
            "attribute": "regex",
            "source": "http://host.docker.internal:8000/redirect?to=https"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    },
    {
        "timestamp": "2026-03-28T00:02:07Z",
        "request": {
            "method": "GET",
            "endpoint": "http://host.docker.internal:8000/juice-shop/node_modules/express/lib/router/styles.css",
            "tag": "link",
            "attribute": "href",
            "source": "http://host.docker.internal:8000/juice-shop/node_modules/express/lib/router/index.js"
        },
        "error": "cause=\"context deadline exceeded\" chain=\"hybrid: could not get dom\""
    }
]
Path(sys.argv[1]).write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in rows), encoding="utf-8")
PY
sqlite3 "$ENG_DIR/cases.db" 'delete from cases;'
KATANA_INGEST_SKIP_START=1 KATANA_INGEST_ONESHOT=1 "$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null
filtered_cases="$(sqlite3 "$ENG_DIR/cases.db" 'select count(*) from cases;')"
[[ "$filtered_cases" == "1" ]] || {
  echo "expected noise-filter replay to keep only 1 real case, got $filtered_cases cases" >&2
  exit 1
}
sqlite3 "$ENG_DIR/cases.db" 'select url from cases;' | grep -q '/rest/admin/application-configuration'
if sqlite3 "$ENG_DIR/cases.db" 'select url from cases;' | grep -q '%5C%22\|/%5C/index.html\|/assets/public/images/w\|/assets/public/images/chunk-24EZLZ4I.js\|/assets/public/images/assets/public/main.js\|/assets/i18n/assets/public/polyfills.js\|\*/kyc-verify\$\|/scripts/lib/\|/Bun/\|/juice-shop/node_modules/express/lib/router/index.js\|/juice-shop/node_modules/express/lib/router/styles.css'; then
  echo "expected malformed katana discoveries to be filtered from replay" >&2
  exit 1
fi

echo "katana ingest replay contracts: ok"
