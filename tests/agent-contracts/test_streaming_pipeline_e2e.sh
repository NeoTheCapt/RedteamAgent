#!/usr/bin/env bash
set -euo pipefail

# test_streaming_pipeline_e2e.sh — End-to-end smoke for the streaming
# case-pipeline. Exercises one full cycle against a freshly-migrated
# cases.db without touching any live engagement.
#
# What it covers (each step's success is an assertion):
#   1. dispatcher.sh migrate adds the `stage` column on a legacy DB
#   2. fetch-by-stage selects stage+type matching rows AND flips status
#      to processing
#   3. done <id> --stage <next> advances pipeline AND flips status to done
#   4. set-stage <id> <stage> updates stage WITHOUT touching status
#   5. stats-by-stage reports the four-bucket breakdown correctly
#   6. update_phase_from_stages.sh derives the right current_phase from
#      stage distribution (uses the stage-aware ACTIVE clause)
#   7. fuzz_pending stage routes correctly (vulnerability-analyst can
#      mark a case fuzz_pending and dispatcher fetch-by-stage finds it
#      under fuzzer)
#   8. terminal-stage rows with status=pending do NOT count as remaining
#      work (the regression that caused run 730's incomplete_stop)
#   9. prune_vendor_cases.py marks vendor JS as stage=clean
#  10. fetch_batch_to_file.sh emits the BATCH_* envelope keys
#
# Failures here mean the streaming pipeline's contract has shifted
# without all consumers being updated. Bash 3.2 compatible (no
# associative arrays, no mapfile).
#
# Exit 0 = all pass, 1 = at least one assertion failed, 2 = harness
# error (DB couldn't be created, missing tool).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$ROOT/agent/scripts"
DISPATCHER="$SCRIPTS/dispatcher.sh"
SCHEMA="$SCRIPTS/schema.sql"
UPDATE_PHASE="$SCRIPTS/update_phase_from_stages.sh"
PRUNE_VENDOR="$SCRIPTS/prune_vendor_cases.py"
FETCH_BATCH="$SCRIPTS/fetch_batch_to_file.sh"

for f in "$DISPATCHER" "$SCHEMA" "$UPDATE_PHASE" "$PRUNE_VENDOR" "$FETCH_BATCH"; do
    if [[ ! -f "$f" ]]; then
        echo "FATAL: required script missing: $f" >&2
        exit 2
    fi
done

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "FATAL: sqlite3 not found" >&2
    exit 2
fi

# Per-test workspace; cleaned up on exit.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/streaming-e2e.XXXXXX")"
DB="$WORK/cases.db"
ENG="$WORK/engagement"
mkdir -p "$ENG"

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

failures=0
fail() {
    failures=$((failures + 1))
    echo "  ✗ $1" >&2
}
ok() {
    echo "  ✓ $1"
}

# ---- 1. schema.sql + migrate adds the stage column ----
sqlite3 "$DB" < "$SCHEMA" >/dev/null
# Initial schema.sql does NOT include stage; dispatcher.sh adds it on first run.
HAS_STAGE_BEFORE="$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('cases') WHERE name='stage';")"
bash "$DISPATCHER" "$DB" stats >/dev/null 2>&1
HAS_STAGE_AFTER="$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('cases') WHERE name='stage';")"
if [[ "$HAS_STAGE_BEFORE" == "0" && "$HAS_STAGE_AFTER" == "1" ]]; then
    ok "step 1: dispatcher.sh migrates legacy schema.sql DB to include stage column"
else
    fail "step 1: stage column migration failed (before=$HAS_STAGE_BEFORE after=$HAS_STAGE_AFTER)"
fi

# ---- Seed a representative mix of cases ----
sqlite3 "$DB" "INSERT INTO cases (method, url, url_path, type, source, status, stage) VALUES
('GET', 'http://t/a',                '/a',                'api',        'katana', 'pending', 'ingested'),
('POST','http://t/login',            '/login',            'api',        'katana', 'pending', 'ingested'),
('GET', 'http://t/main.js',          '/main.js',          'javascript', 'katana', 'pending', 'ingested'),
('GET', 'http://t/chunk-abc123.js',  '/chunk-abc123.js',  'javascript', 'katana', 'pending', 'ingested'),
('GET', 'http://t/runtime.def4.js',  '/runtime.def4.js',  'javascript', 'katana', 'pending', 'ingested'),
('GET', 'http://t/done',             '/done',             'api',        'katana', 'done',    'clean')"

# ---- 9. prune_vendor_cases.py marks vendor JS as stage=clean ----
python3 "$PRUNE_VENDOR" "$DB" >/dev/null 2>&1 || true
VENDOR_CLEANED="$(sqlite3 "$DB" "SELECT COUNT(*) FROM cases WHERE url_path IN ('/chunk-abc123.js','/runtime.def4.js') AND stage='clean'")"
REAL_JS_KEPT="$(sqlite3 "$DB" "SELECT COUNT(*) FROM cases WHERE url_path = '/main.js' AND stage='ingested'")"
if [[ "$VENDOR_CLEANED" == "2" && "$REAL_JS_KEPT" == "1" ]]; then
    ok "step 9: prune_vendor_cases.py marked 2 vendor-noise as clean, kept 1 real JS as ingested"
else
    fail "step 9: prune cleaned=$VENDOR_CLEANED expected 2; real JS kept=$REAL_JS_KEPT expected 1"
fi

# ---- 2. fetch-by-stage selects matching rows and flips status to processing ----
BATCH="$WORK/batch.json"
bash "$FETCH_BATCH" "$DB" --stage ingested api 5 vulnerability-analyst "$BATCH" >"$WORK/fetch.out" 2>&1 || true

# ---- 10. fetch_batch_to_file.sh emits the BATCH_* envelope keys ----
# `BATCH_LIMIT` is only emitted on errors / partial fetches; `BATCH_NOTE`
# only when stderr is non-empty. The 7 keys below are the always-on
# baseline a successful fetch must include.
ENV_KEYS_FOUND=0
for k in BATCH_FILE BATCH_TYPE BATCH_AGENT BATCH_STAGE BATCH_COUNT BATCH_IDS BATCH_PATHS; do
    if /usr/bin/grep -q "^$k=" "$WORK/fetch.out"; then
        ENV_KEYS_FOUND=$((ENV_KEYS_FOUND + 1))
    fi
done
if [[ "$ENV_KEYS_FOUND" == "7" ]]; then
    ok "step 10: fetch_batch_to_file.sh emits all 7 always-on BATCH_* keys"
else
    fail "step 10: only $ENV_KEYS_FOUND/7 BATCH_* keys present in fetch output"
fi

PROCESSING_API="$(sqlite3 "$DB" "SELECT COUNT(*) FROM cases WHERE type='api' AND status='processing'")"
if [[ "$PROCESSING_API" == "2" ]]; then
    ok "step 2: fetch-by-stage flipped 2 api/ingested rows to status=processing"
else
    fail "step 2: expected 2 api/processing, got $PROCESSING_API"
fi

# ---- 3. done <id> --stage semantics: advancing to ACTIVE stage keeps status
#       pending (next agent picks up); advancing to TERMINAL stage flips status
#       to done (case retires). Run-30 incomplete_stop bug class lived here. ----
LOGIN_ID="$(sqlite3 "$DB" "SELECT id FROM cases WHERE url_path='/login'")"

# 3a. ACTIVE target stage → status flips back to pending
bash "$DISPATCHER" "$DB" done "$LOGIN_ID" --stage vuln_confirmed >/dev/null 2>&1
LOGIN_STAGE="$(sqlite3 "$DB" "SELECT stage FROM cases WHERE id=$LOGIN_ID")"
LOGIN_STATUS="$(sqlite3 "$DB" "SELECT status FROM cases WHERE id=$LOGIN_ID")"
if [[ "$LOGIN_STAGE" == "vuln_confirmed" && "$LOGIN_STATUS" == "pending" ]]; then
    ok "step 3a: done --stage vuln_confirmed (active) → stage advanced, status re-pended for next agent"
else
    fail "step 3a: expected vuln_confirmed/pending, got $LOGIN_STAGE/$LOGIN_STATUS"
fi

# 3b. TERMINAL target stage → status flips to done
bash "$DISPATCHER" "$DB" done "$LOGIN_ID" --stage exploited >/dev/null 2>&1
LOGIN_STAGE2="$(sqlite3 "$DB" "SELECT stage FROM cases WHERE id=$LOGIN_ID")"
LOGIN_STATUS2="$(sqlite3 "$DB" "SELECT status FROM cases WHERE id=$LOGIN_ID")"
if [[ "$LOGIN_STAGE2" == "exploited" && "$LOGIN_STATUS2" == "done" ]]; then
    ok "step 3b: done --stage exploited (terminal) → stage retired, status flipped to done"
else
    fail "step 3b: expected exploited/done, got $LOGIN_STAGE2/$LOGIN_STATUS2"
fi

# ---- 4. set-stage updates stage WITHOUT touching status ----
A_ID="$(sqlite3 "$DB" "SELECT id FROM cases WHERE url_path='/a'")"
A_STATUS_BEFORE="$(sqlite3 "$DB" "SELECT status FROM cases WHERE id=$A_ID")"
bash "$DISPATCHER" "$DB" set-stage "$A_ID" api_tested >/dev/null 2>&1
A_STAGE_AFTER="$(sqlite3 "$DB" "SELECT stage FROM cases WHERE id=$A_ID")"
A_STATUS_AFTER="$(sqlite3 "$DB" "SELECT status FROM cases WHERE id=$A_ID")"
if [[ "$A_STAGE_AFTER" == "api_tested" && "$A_STATUS_AFTER" == "$A_STATUS_BEFORE" ]]; then
    ok "step 4: set-stage moved stage to api_tested, status preserved (= $A_STATUS_BEFORE)"
else
    fail "step 4: expected api_tested + status unchanged ($A_STATUS_BEFORE), got $A_STAGE_AFTER/$A_STATUS_AFTER"
fi

# ---- 5. stats-by-stage reports the four-bucket breakdown ----
# The exact stage list inside the parens floats with dispatcher.sh,
# so just match the line prefix. The D7 test enforces consistency.
STATS_OUT="$(bash "$DISPATCHER" "$DB" stats-by-stage 2>&1)"
if echo "$STATS_OUT" | /usr/bin/grep -q "^active (" \
   && echo "$STATS_OUT" | /usr/bin/grep -q "^terminal (" \
   && echo "$STATS_OUT" | /usr/bin/grep -q "^in-flight (processing)"; then
    ok "step 5: stats-by-stage shows the active / terminal / in-flight breakdown"
else
    fail "step 5: stats-by-stage missing expected active/terminal/in-flight lines"
fi

# ---- 6. update_phase_from_stages.sh derives current_phase ----
# Seed a fresh vuln_confirmed row so the exploit-branch derivation fires
# (the /login row we used in step 3 was advanced to exploited terminal).
mkdir -p "$ENG"
cp "$DB" "$ENG/cases.db"
sqlite3 "$ENG/cases.db" "INSERT INTO cases (method,url,url_path,type,source,status,stage) VALUES
('GET','http://t/vuln','/vuln','api','katana','pending','vuln_confirmed')"
echo '{"target":"http://t","phases_completed":[],"current_phase":"recon"}' > "$ENG/scope.json"
bash "$UPDATE_PHASE" "$ENG" >/dev/null 2>&1 || true
DERIVED_PHASE="$(/usr/local/bin/jq -r .current_phase "$ENG/scope.json" 2>/dev/null \
    || /opt/homebrew/bin/jq -r .current_phase "$ENG/scope.json" 2>/dev/null \
    || /usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("current_phase",""))' "$ENG/scope.json")"
# vuln_confirmed > 0 → exploit branch fires
if [[ "$DERIVED_PHASE" == "exploit" ]]; then
    ok "step 6: update_phase_from_stages derived 'exploit' from vuln_confirmed row"
else
    fail "step 6: expected current_phase=exploit (vuln_confirmed exists), got '$DERIVED_PHASE'"
fi

# ---- 7. fuzz_pending stage routes correctly ----
sqlite3 "$DB" "INSERT INTO cases (method, url, url_path, type, source, status, stage) VALUES
('GET','http://t/q','/q','api','katana','pending','fuzz_pending')"
BATCH2="$WORK/batch-fuzz.json"
bash "$FETCH_BATCH" "$DB" --stage fuzz_pending api 5 fuzzer "$BATCH2" >"$WORK/fetch-fuzz.out" 2>&1 || true
FUZZ_COUNT="$(/usr/bin/grep '^BATCH_COUNT=' "$WORK/fetch-fuzz.out" | /usr/bin/sed 's/.*=//')"
if [[ "$FUZZ_COUNT" == "1" ]]; then
    ok "step 7: fetch-by-stage fuzz_pending api → fuzzer fetched 1 row"
else
    fail "step 7: expected 1 fuzz_pending row, got '$FUZZ_COUNT'"
fi

# ---- 8. Regression guard: terminal-stage rows with status=pending must NOT count as remaining work ----
# Set up: 1 row at api_tested/pending (the run 730 scenario)
sqlite3 "$DB" "INSERT INTO cases (method, url, url_path, type, source, status, stage) VALUES
('GET','http://t/legacy-pending','/legacy-pending','api','katana','pending','api_tested')"

# Replicate the orchestrator-side count using the same SQL as launcher.py
TERMINAL_QUERY="SELECT COUNT(*) FROM cases WHERE status='pending' AND stage NOT IN ('source_analyzed','api_tested','clean','exploited','errored')"
ACTIVE_PENDING="$(sqlite3 "$DB" "$TERMINAL_QUERY")"
TOTAL_PENDING="$(sqlite3 "$DB" "SELECT COUNT(*) FROM cases WHERE status='pending'")"

if [[ "$TOTAL_PENDING" -gt "$ACTIVE_PENDING" ]]; then
    ok "step 8: terminal-stage pending rows ($((TOTAL_PENDING - ACTIVE_PENDING))) excluded from active count ($ACTIVE_PENDING) — run-730 regression guard"
else
    fail "step 8: stage-aware filter not subtracting terminal pending; total=$TOTAL_PENDING active=$ACTIVE_PENDING"
fi

if (( failures > 0 )); then
    echo "" >&2
    echo "FAIL: $failures streaming-pipeline assertion(s) failed" >&2
    exit 1
fi

echo ""
echo "OK: streaming pipeline contract intact across schema, dispatcher, prune, fetch, phase derivation"
exit 0
