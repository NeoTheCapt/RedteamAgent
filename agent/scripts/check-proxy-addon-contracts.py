#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import sys
import tempfile
import types


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

    path = pathlib.Path("agent/scripts/proxy_addon.py")
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


mod = load_proxy_addon()
collector = mod.CaseCollector()

# Direct classification contract: response content type should be enough to classify a page/data response.
page_type = collector._classify_type("GET", "https://example.test/dashboard", "text/html", {})
if page_type != "page":
    fail(f"expected text/html response to classify as page, got {page_type!r}")

data_type = collector._classify_type("GET", "https://example.test/download", "application/json", {})
if data_type != "data":
    fail(f"expected application/json GET response without /api/ path to classify as data, got {data_type!r}")

# End-to-end response() contract: inserted rows should use response content type, not request content type.
with tempfile.TemporaryDirectory() as tmp:
    eng = pathlib.Path(tmp)
    (eng / "scope.json").write_text(json.dumps({"scope": ["example.test"]}))
    conn = mod.sqlite3.connect(eng / "cases.db")
    conn.executescript(pathlib.Path("agent/scripts/schema.sql").read_text())
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

print("[OK] Proxy addon classification contracts hold")
