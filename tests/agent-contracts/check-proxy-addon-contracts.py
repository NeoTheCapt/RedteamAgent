#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import types

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"


def load_proxy_addon():
    mitmproxy = types.ModuleType("mitmproxy")
    http = types.ModuleType("http")
    ctx = types.SimpleNamespace(
        options=types.SimpleNamespace(engagement_dir=""),
        log=types.SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None, error=lambda *a, **k: None),
    )
    mitmproxy.http = http
    mitmproxy.ctx = ctx
    sys.modules["mitmproxy"] = mitmproxy
    sys.modules["mitmproxy.http"] = http
    sys.modules["mitmproxy.ctx"] = mitmproxy.ctx

    path = AGENT_DIR / "scripts" / "proxy_addon.py"
    spec = importlib.util.spec_from_file_location("proxy_addon_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Headers(dict):
    def get_all(self, key):
        val = self.get(key, [])
        if isinstance(val, list):
            return val
        return [val]


class Message:
    def __init__(self, headers=None, body=b"", method="GET", pretty_url="https://example.test/"):
        self.headers = Headers(headers or {})
        self._body = body
        self.method = method
        self.pretty_url = pretty_url

    def get_content(self, raise_if_missing=False):
        return self._body


class Response:
    def __init__(self, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = Headers(headers or {})
        self._body = body

    def get_content(self, raise_if_missing=False):
        return self._body


class Flow:
    def __init__(self, request, response):
        self.request = request
        self.response = response


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def shell_classify(method, url_path, content_type="", body_snippet=""):
    cmd = (
        f"source '{AGENT_DIR / 'scripts' / 'lib' / 'classify.sh'}' && "
        "classify_type \"$1\" \"$2\" \"$3\" \"$4\""
    )
    return subprocess.check_output(
        ["bash", "-lc", cmd, "bash", method, url_path, content_type, body_snippet],
        text=True,
    ).strip()


def shell_sig(query_json, body_json):
    cmd = (
        f"source '{AGENT_DIR / 'scripts' / 'lib' / 'params.sh'}' && "
        "generate_params_sig \"$1\" \"$2\""
    )
    return subprocess.check_output(
        ["bash", "-lc", cmd, "bash", query_json, body_json],
        text=True,
    ).strip()


mod = load_proxy_addon()
collector = mod.CaseCollector()

# Classification contract: proxy and shell producers should agree on routing.
cases = [
    ("GET", "https://example.test/dashboard", "text/html", "", "page"),
    ("GET", "https://example.test/download", "application/json", "", "data"),
    ("POST", "https://example.test/session", "application/json", "", "api"),
    ("GET", "https://example.test/api/users", "text/plain", "", "api"),
    ("GET", "https://example.test/assets/app.js", "", "", "javascript"),
]

for method, path, content_type, body_snippet, expected in cases:
    proxy_type = collector._classify_type(method, path, content_type, {})
    shell_type = shell_classify(method, path, content_type, body_snippet)
    if proxy_type != expected:
        fail(
            f"expected proxy classification for {method} {path} to be {expected!r}, got {proxy_type!r}"
        )
    if shell_type != expected:
        fail(
            f"expected shell classification for {method} {path} to be {expected!r}, got {shell_type!r}"
        )

# Dedup signature contract: proxy and shell helpers should produce the same hash.
query_json = json.dumps({"id": "1", "debug": "1"})
body_json = json.dumps({"id": "2", "name": "alice"})
proxy_sig = collector._generate_sig(query_json, body_json)
expected_sig = shell_sig(query_json, body_json)
if proxy_sig != expected_sig:
    fail(f"expected matching params_key_sig, got proxy={proxy_sig!r} shell={expected_sig!r}")

# End-to-end response() contract: inserted rows should use response content type, not request content type.
with tempfile.TemporaryDirectory() as tmp:
    eng = pathlib.Path(tmp)
    (eng / "scope.json").write_text(json.dumps({"scope": ["example.test"]}))
    conn = mod.sqlite3.connect(eng / "cases.db")
    conn.executescript((AGENT_DIR / "scripts" / "schema.sql").read_text())
    conn.close()

    collector.engagement_dir = str(eng)
    collector._init_db()
    collector._load_scope()

    req = Message(headers={}, body=b"", method="GET", pretty_url="https://example.test/dashboard")
    resp = Response(status_code=200, headers={"content-type": "text/html"}, body=b"<html>ok</html>")
    collector.response(Flow(req, resp))

    row = collector.db.execute("SELECT type, content_type FROM cases").fetchone()
    if row is None:
        fail("expected proxy addon to insert a case row")
    if row[0] != "page":
        fail(f"expected inserted case type to be 'page', got {row[0]!r}")
    if row[1] != "text/html":
        fail(f"expected stored content_type to come from response, got {row[1]!r}")

    login_req = Message(
        headers={"content-type": "application/json"},
        body=b'{"username":"demo","password":"pass"}',
        method="POST",
        pretty_url="https://example.test/login",
    )
    login_resp = Response(
        status_code=200,
        headers={"content-type": "application/json"},
        body=b'{"access_token":"secret-token"}',
    )
    collector.response(Flow(login_req, login_resp))

    auth_json = json.loads((eng / "auth.json").read_text())
    if auth_json.get("tokens", {}).get("access_token") != "secret-token":
        fail("expected proxy addon to persist detected access_token in auth.json.tokens")
    if auth_json.get("headers", {}).get("Authorization") != "Bearer secret-token":
        fail("expected proxy addon to promote detected access_token into headers.Authorization")

    req2 = Message(
        headers={},
        body=b"",
        method="GET",
        pretty_url="https://example.test/users/1234567890abcdef12345678/orders/42",
    )
    resp2 = Response(status_code=200, headers={"content-type": "text/html"}, body=b"<html>ok</html>")
    collector.response(Flow(req2, resp2))
    path_row = collector.db.execute(
        "SELECT path_params FROM cases WHERE url_path = '/users/1234567890abcdef12345678/orders/42'"
    ).fetchone()
    expected_path_params = {
        "seg_2": "1234567890abcdef12345678",
        "seg_4": "42",
    }
    if path_row is None:
        fail("expected proxy addon to insert path-param case row")
    if json.loads(path_row[0]) != expected_path_params:
        fail(
            f"expected path_params to match shell seg_N object shape, got {path_row[0]!r}"
        )

print("[OK] Proxy addon classification contracts hold")
