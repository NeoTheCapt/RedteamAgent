import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_api_audit_refreshes_stale_token_before_reporting_auth_finding():
    script = (ROOT / "scripts" / "audit_orchestrator_api.sh").read_text()
    preflight = script[script.index('auth_probe_code="$(_curl_authed_code "GET" "/auth/me")"') : script.index('# --- GET /auth/me')]

    assert "ensure_orchestrator_token" in preflight
    assert re.search(r'auth_probe_code=.*_curl_authed_code "GET" "/auth/me"', preflight)
    assert preflight.index("ensure_orchestrator_token") < preflight.index('audit_append_finding "API-AUTH"')
    assert "after refresh attempt" in preflight


def test_features_audit_retries_auth_me_with_refreshed_scheduler_token():
    script = (ROOT / "scripts" / "audit_orchestrator_features.py").read_text()
    assert "def refresh_scheduler_token()" in script
    assert "ensure_orchestrator_token" in script
    assert "resolve_token(prefer_env=False)" in script

    start = script.index('probe_status, _ = _api(base_url, "GET", "/auth/me", token=token)')
    end = script.index('write_report(report_path, cycle_id)', start)
    preflight = script[start:end]
    assert "if probe_status != 200 and refresh_scheduler_token():" in preflight
    assert preflight.index("refresh_scheduler_token") < preflight.index("record_fail")
    assert "after refresh attempt" in preflight
