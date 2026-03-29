"""mitmproxy addon — intercepts HTTP traffic and queues cases into SQLite.

Load with:
    mitmdump -p 8080 -s scripts/proxy_addon.py --set engagement_dir=engagements/<date>/
"""

import json
import hashlib
import sqlite3
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, unquote_plus

from mitmproxy import http, ctx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOISE_DOMAINS = {
    "google-analytics.com",
    "www.google-analytics.com",
    "googletagmanager.com",
    "www.googletagmanager.com",
    "facebook.net",
    "connect.facebook.net",
    "doubleclick.net",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "ajax.googleapis.com",
}

NOISE_PATH_RE = re.compile(r"(\.gif\?|pixel|beacon)", re.IGNORECASE)

BODY_TRUNCATE = 100 * 1024  # 100 KB

SKIP_TYPES = {"image", "video", "font", "archive"}

BINARY_PREFIXES = ("image/", "video/", "audio/", "font/")

LOGIN_URL_RE = re.compile(r"(login|auth|signin|session|token)", re.IGNORECASE)

TOKEN_KEYS_RE = re.compile(r"(token|access_token|jwt)", re.IGNORECASE)
BEARER_TOKEN_KEYS_RE = re.compile(r"(access_token|id_token|jwt|token)", re.IGNORECASE)

# Maps file extensions / content-type fragments to a classification label.
# Order matters — first match wins (highest priority first).
_EXT_GRAPHQL = {"/graphql"}
_EXT_WS = set()  # detected via Upgrade header
_EXT_API = {"/api/", "/rest/", "/v1/", "/v2/", "/v3/"}
_EXT_UPLOAD_CT = {"multipart/form-data"}
_EXT_FORM_CT = {"application/x-www-form-urlencoded"}
_EXT_JS = {".js", ".mjs", ".cjs"}
_EXT_CSS = {".css"}
_EXT_PAGE = {".html", ".htm", ".xhtml", ".php", ".asp", ".aspx", ".jsp"}
_EXT_DATA = {".json", ".xml", ".csv", ".yaml", ".yml"}
_EXT_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp"}
_EXT_VIDEO = {".mp4", ".webm", ".avi", ".mov", ".flv"}
_EXT_FONT = {".woff", ".woff2", ".ttf", ".eot", ".otf"}
_EXT_ARCHIVE = {".zip", ".gz", ".tar", ".rar", ".7z", ".bz2"}

# Dynamic path-segment patterns
_DYNAMIC_RE = re.compile(
    r"(?:^[0-9]+$"  # numeric ID
    r"|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"  # UUID
    r"|^[0-9a-f]{24,}$)",  # hex 24+ chars (e.g. MongoDB ObjectId)
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Addon
# ---------------------------------------------------------------------------


class CaseCollector:
    """Collects HTTP request/response pairs and stores them in cases.db."""

    def __init__(self):
        self.db: sqlite3.Connection | None = None
        self.scope: list[str] = []
        self.engagement_dir: str = ""

    # -- mitmproxy lifecycle ------------------------------------------------

    def load(self, loader):
        loader.add_option(
            "engagement_dir", str, "", "Path to engagement directory"
        )

    def configure(self, updates):
        if "engagement_dir" in updates:
            self.engagement_dir = ctx.options.engagement_dir
            if self.engagement_dir:
                self._init_db()
                self._load_scope()

    # -- initialisation -----------------------------------------------------

    def _init_db(self):
        db_path = os.path.join(self.engagement_dir, "cases.db")
        try:
            self.db = sqlite3.connect(db_path, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
            ctx.log.info(f"proxy_addon: connected to {db_path}")
        except sqlite3.OperationalError as exc:
            ctx.log.error(f"proxy_addon: cannot open DB — {exc}")
            self.db = None

    def _load_scope(self):
        scope_path = os.path.join(self.engagement_dir, "scope.json")
        try:
            with open(scope_path, "r") as fh:
                data = json.load(fh)
            # scope.json is expected to be a list of hostname patterns
            # e.g. ["example.com", "*.example.com"]
            if isinstance(data, list):
                self.scope = data
            elif isinstance(data, dict) and "scope" in data:
                self.scope = data["scope"]
            else:
                self.scope = []
            ctx.log.info(f"proxy_addon: loaded {len(self.scope)} scope entries")
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            ctx.log.warn(f"proxy_addon: cannot load scope — {exc}")
            self.scope = []

    # -- checks -------------------------------------------------------------

    def _is_in_scope(self, hostname: str) -> bool:
        if not self.scope:
            return True  # no scope file ⇒ allow all
        hostname = hostname.lower()
        for pattern in self.scope:
            pattern = pattern.lower()
            if pattern.startswith("*."):
                suffix = pattern[1:]  # e.g. ".example.com"
                if hostname == pattern[2:] or hostname.endswith(suffix):
                    return True
            else:
                if hostname == pattern:
                    return True
        return False

    def _is_noise(self, hostname: str, path: str) -> bool:
        hostname = hostname.lower()
        for nd in NOISE_DOMAINS:
            if hostname == nd or hostname.endswith("." + nd):
                return True
        if NOISE_PATH_RE.search(path):
            return True
        return False

    # -- classification -----------------------------------------------------

    def _classify_type(
        self, method: str, path: str, content_type: str, req_headers: dict
    ) -> str:
        ct = (content_type or "").lower()
        path_lower = path.lower()

        # Strip query string for extension matching
        base_path = path_lower.split("?")[0]

        # graphql
        if any(seg in base_path for seg in _EXT_GRAPHQL):
            return "graphql"

        # websocket
        if req_headers.get("upgrade", "").lower() == "websocket":
            return "websocket"

        # api — path heuristic or JSON content-type on non-page paths
        if any(seg in base_path for seg in _EXT_API):
            return "api"
        if "application/json" in ct and method in ("POST", "PUT", "PATCH", "DELETE"):
            return "api"

        # upload
        if any(seg in ct for seg in _EXT_UPLOAD_CT):
            return "upload"

        # form
        if any(seg in ct for seg in _EXT_FORM_CT):
            return "form"

        # Response content-type should override extension-based asset guesses.
        # This prevents SPA fallback HTML from being treated as javascript/stylesheet
        # just because the requested path ends with .js/.css.
        _, ext = os.path.splitext(base_path)
        if "text/html" in ct or "application/xhtml" in ct or "image/svg+xml" in ct:
            return "page"
        if "application/json" in ct or "text/xml" in ct or "application/xml" in ct or "text/csv" in ct or "application/pdf" in ct or "text/plain" in ct or "application/ld+json" in ct or "text/markdown" in ct:
            return "data"
        if ct.startswith("image/") and "svg" not in ct:
            return "image"
        if ct.startswith("video/") or ct.startswith("audio/"):
            return "video"
        if ct.startswith("font/") or "application/vnd.ms-fontobject" in ct:
            return "font"
        if any(seg in ct for seg in ("zip", "gzip", "tar", "rar", "7z", "bzip")):
            return "archive"
        if ext in _EXT_JS or "text/javascript" in ct or "application/javascript" in ct:
            return "javascript"
        if ext in _EXT_CSS or "text/css" in ct:
            return "stylesheet"
        if ext in _EXT_PAGE:
            return "page"
        if ext in _EXT_DATA:
            return "data"
        if ext in _EXT_IMAGE:
            return "image"
        if ext in _EXT_VIDEO:
            return "video"
        if ext in _EXT_FONT:
            return "font"
        if ext in _EXT_ARCHIVE:
            return "archive"

        return "unknown"

    # -- parameter extraction -----------------------------------------------

    def _extract_params(self, flow: http.HTTPFlow) -> dict:
        req = flow.request
        parsed = urlparse(req.pretty_url)

        # query params
        query_params = {}
        if parsed.query:
            query_params = {k: v if len(v) > 1 else v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}

        # body params
        body_params = {}
        ct = (req.headers.get("content-type", "") or "").lower()
        raw_body = req.get_content(raise_if_missing=False) or b""
        if raw_body:
            if "application/x-www-form-urlencoded" in ct:
                try:
                    body_params = {
                        k: v if len(v) > 1 else v[0]
                        for k, v in parse_qs(raw_body.decode("utf-8", errors="replace"), keep_blank_values=True).items()
                    }
                except Exception:
                    pass
            elif "application/json" in ct or "text/json" in ct:
                try:
                    body_params = json.loads(raw_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        # path params — dynamic segments
        path_parts = [seg for seg in parsed.path.split("/") if seg]
        path_params = {
            f"seg_{idx}": seg
            for idx, seg in enumerate(path_parts, start=1)
            if _DYNAMIC_RE.match(seg)
        }

        # cookie params
        cookie_params = {}
        cookie_header = req.headers.get("cookie", "")
        if cookie_header:
            for pair in cookie_header.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookie_params[k.strip()] = v.strip()

        return {
            "query_params": json.dumps(query_params) if query_params else None,
            "body_params": json.dumps(body_params) if body_params else None,
            "path_params": json.dumps(path_params) if path_params else None,
            "cookie_params": json.dumps(cookie_params) if cookie_params else None,
        }

    # -- dedup signature ----------------------------------------------------

    def _generate_sig(self, query_json: str | None, body_json: str | None) -> str:
        keys: list[str] = []
        if query_json:
            try:
                q = json.loads(query_json)
                if isinstance(q, dict):
                    keys.extend(q.keys())
            except json.JSONDecodeError:
                pass
        if body_json:
            try:
                b = json.loads(body_json)
                if isinstance(b, dict):
                    keys.extend(b.keys())
            except json.JSONDecodeError:
                pass
        return hashlib.md5(",".join(sorted(set(keys))).encode()).hexdigest()

    # -- body save policy ---------------------------------------------------

    def _apply_body_policy(self, body: bytes | None, content_type: str) -> str | None:
        if not body:
            return None
        ct = (content_type or "").lower()
        # Skip binary types entirely
        if any(ct.startswith(p) for p in BINARY_PREFIXES):
            return None
        # Only save text-ish bodies
        saveable = (
            "json" in ct
            or "form-urlencoded" in ct
            or "html" in ct
            or "xml" in ct
            or "text/" in ct
        )
        if not saveable:
            return None
        text = body[:BODY_TRUNCATE].decode("utf-8", errors="replace")
        return text

    # -- login detection ----------------------------------------------------

    def _detect_login(self, flow: http.HTTPFlow):
        req = flow.request
        resp = flow.response
        if req.method != "POST" or not resp:
            return
        if not LOGIN_URL_RE.search(req.pretty_url):
            return
        if resp.status_code and resp.status_code >= 400:
            return

        auth_data: dict = {}
        auth_path = os.path.join(self.engagement_dir, "auth.json")

        # Load existing auth.json if present
        if os.path.exists(auth_path):
            try:
                with open(auth_path, "r") as fh:
                    auth_data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                auth_data = {}

        updated = False

        # Check Set-Cookie headers
        set_cookies = resp.headers.get_all("set-cookie")
        if set_cookies:
            cookies = {}
            for sc in set_cookies:
                parts = sc.split(";")[0]
                if "=" in parts:
                    k, v = parts.split("=", 1)
                    cookies[k.strip()] = v.strip()
            if cookies:
                auth_data["cookies"] = cookies
                updated = True

        # Check response body for tokens
        resp_body = resp.get_content(raise_if_missing=False) or b""
        if resp_body:
            try:
                body_json = json.loads(resp_body)
                if isinstance(body_json, dict):
                    for key in list(body_json.keys()):
                        if TOKEN_KEYS_RE.search(key):
                            token_value = body_json[key]
                            auth_data.setdefault("tokens", {})[key] = token_value
                            if (
                                isinstance(token_value, str)
                                and token_value
                                and BEARER_TOKEN_KEYS_RE.search(key)
                            ):
                                auth_data.setdefault("headers", {})
                                if "Authorization" not in auth_data["headers"]:
                                    bearer_value = (
                                        token_value
                                        if token_value.lower().startswith("bearer ")
                                        else f"Bearer {token_value}"
                                    )
                                    auth_data["headers"]["Authorization"] = bearer_value
                            updated = True
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if updated:
            try:
                with open(auth_path, "w") as fh:
                    json.dump(auth_data, fh, indent=2)
                ctx.log.info("proxy_addon: updated auth.json")
            except OSError as exc:
                ctx.log.warn(f"proxy_addon: cannot write auth.json — {exc}")

    # -- DB insert ----------------------------------------------------------

    def _insert_case(
        self,
        method: str,
        url: str,
        url_path: str,
        params: dict,
        headers: str,
        body: str | None,
        content_type: str,
        content_length: int,
        response_status: int,
        response_headers: str,
        response_size: int,
        response_snippet: str | None,
        case_type: str,
        status: str,
        params_key_sig: str,
    ):
        if not self.db:
            return
        try:
            self.db.execute(
                """INSERT OR IGNORE INTO cases (
                    method, url, url_path,
                    query_params, body_params, path_params, cookie_params,
                    headers, body, content_type, content_length,
                    response_status, response_headers, response_size, response_snippet,
                    type, source, status, params_key_sig
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, 'proxy', ?, ?
                )""",
                (
                    method,
                    url,
                    url_path,
                    params.get("query_params"),
                    params.get("body_params"),
                    params.get("path_params"),
                    params.get("cookie_params"),
                    headers,
                    body,
                    content_type,
                    content_length,
                    response_status,
                    response_headers,
                    response_size,
                    response_snippet,
                    case_type,
                    status,
                    params_key_sig,
                ),
            )
            self.db.commit()
        except sqlite3.OperationalError as exc:
            ctx.log.warn(f"proxy_addon: DB busy/error — {exc}")

    # -- main entry point ---------------------------------------------------

    def response(self, flow: http.HTTPFlow):
        """Called by mitmproxy for every completed request/response pair."""
        if not self.db:
            return

        req = flow.request
        resp = flow.response
        if not resp:
            return

        parsed = urlparse(req.pretty_url)
        hostname = parsed.hostname or ""
        path = parsed.path or "/"

        # Scope check
        if not self._is_in_scope(hostname):
            return

        # Noise filter
        if self._is_noise(hostname, req.pretty_url):
            return

        # Login detection (side-effect: may write auth.json)
        self._detect_login(flow)

        # Extract parameters
        params = self._extract_params(flow)

        # Request headers as JSON
        req_headers_dict = dict(req.headers)
        req_headers_json = json.dumps(req_headers_dict)

        # Prefer response content type for classification/storage. Request content
        # type is often empty for GETs and would misclassify normal pages as unknown.
        content_type = resp.headers.get("content-type", "") or req.headers.get("content-type", "") or ""
        raw_req_body = req.get_content(raise_if_missing=False) or b""
        content_length = len(raw_req_body)

        # Classification
        case_type = self._classify_type(req.method, req.pretty_url, content_type, req_headers_dict)

        # Body save policy
        saved_body = self._apply_body_policy(raw_req_body, content_type)

        # Response info
        response_status = resp.status_code
        resp_headers_json = json.dumps(dict(resp.headers))
        resp_body = resp.get_content(raise_if_missing=False) or b""
        response_size = len(resp_body)

        # Response snippet: first 512 bytes of text responses
        response_snippet = None
        resp_ct = (resp.headers.get("content-type", "") or "").lower()
        if resp_body and not any(resp_ct.startswith(p) for p in BINARY_PREFIXES):
            response_snippet = resp_body[:512].decode("utf-8", errors="replace")

        # Dedup signature
        params_key_sig = self._generate_sig(
            params.get("query_params"), params.get("body_params")
        )

        # Status
        status = "skipped" if case_type in SKIP_TYPES else "pending"

        # Insert
        self._insert_case(
            method=req.method,
            url=req.pretty_url,
            url_path=path,
            params=params,
            headers=req_headers_json,
            body=saved_body,
            content_type=content_type,
            content_length=content_length,
            response_status=response_status,
            response_headers=resp_headers_json,
            response_size=response_size,
            response_snippet=response_snippet,
            case_type=case_type,
            status=status,
            params_key_sig=params_key_sig,
        )


addons = [CaseCollector()]
