#!/usr/bin/env python3
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def unwrap_value(payload: Any) -> Any:
    if isinstance(payload, dict) and "value" in payload:
        return payload["value"]
    return payload


ELEMENT_REFERENCE_KEYS = ("element-6066-11e4-a52e-4f735466cecf", "ELEMENT")


def extract_element_reference(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise RuntimeError(f"webdriver element reference missing from payload: {payload!r}")
    for key in ELEMENT_REFERENCE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    raise RuntimeError(f"webdriver element reference missing from payload: {payload!r}")


class WebDriverClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session_id = ""

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"webdriver {method} {path} failed: HTTP {exc.code}: {body}") from exc
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return raw
        value = unwrap_value(parsed)
        if isinstance(value, dict) and value.get("error"):
            raise RuntimeError(
                f"webdriver {method} {path} error: {value.get('error')}: {value.get('message')}"
            )
        return value

    def create_session(self, chrome_binary: str | None, user_data_dir: Path) -> None:
        args = [
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1440,1080",
            f"--user-data-dir={user_data_dir}",
        ]
        options: dict[str, Any] = {"args": args}
        if chrome_binary:
            options["binary"] = chrome_binary
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "chrome",
                    "goog:chromeOptions": options,
                    "acceptInsecureCerts": True,
                    "pageLoadStrategy": "normal",
                }
            }
        }
        value = self._request("POST", "/session", payload)
        self.session_id = value.get("sessionId") or ""
        if not self.session_id:
            raise RuntimeError(f"failed to create webdriver session: {value}")

    def close(self) -> None:
        if not self.session_id:
            return
        try:
            self._request("DELETE", f"/session/{self.session_id}")
        except Exception:
            pass
        self.session_id = ""

    def navigate(self, url: str) -> None:
        self._request("POST", f"/session/{self.session_id}/url", {"url": url})

    def current_url(self) -> str:
        return str(self._request("GET", f"/session/{self.session_id}/url"))

    def title(self) -> str:
        return str(self._request("GET", f"/session/{self.session_id}/title"))

    def page_source(self) -> str:
        return str(self._request("GET", f"/session/{self.session_id}/source"))

    def screenshot(self) -> bytes:
        encoded = str(self._request("GET", f"/session/{self.session_id}/screenshot"))
        return base64.b64decode(encoded)

    def add_cookie(self, cookie: dict[str, Any]) -> None:
        self._request("POST", f"/session/{self.session_id}/cookie", {"cookie": cookie})

    def execute(self, script: str, args: list[Any] | None = None) -> Any:
        return self._request(
            "POST",
            f"/session/{self.session_id}/execute/sync",
            {"script": script, "args": args or []},
        )

    def find_element(self, using: str, value: str) -> Any:
        return self._request(
            "POST",
            f"/session/{self.session_id}/element",
            {"using": using, "value": value},
        )

    def find_element_css(self, selector: str) -> Any:
        return self.find_element("css selector", selector)

    def click_element(self, element: Any) -> None:
        element_ref = urllib.parse.quote(extract_element_reference(element), safe="")
        self._request("POST", f"/session/{self.session_id}/element/{element_ref}/click", {})


class StepError(RuntimeError):
    pass


class BrowserFlow:
    def __init__(self, client: WebDriverClient, output_dir: Path):
        self.client = client
        self.output_dir = output_dir
        self.steps_run: list[dict[str, Any]] = []

    def record(self, action: str, **extra: Any) -> None:
        item = {"action": action}
        item.update(extra)
        self.steps_run.append(item)

    def wait_for_document(self, timeout_ms: int) -> None:
        self.wait_for_js_true(
            "return document.readyState === 'complete' || document.readyState === 'interactive';",
            timeout_ms=timeout_ms,
            reason="document readyState",
        )

    def wait_for_js_result(
        self,
        script: str,
        timeout_ms: int,
        reason: str,
        args: list[Any] | None = None,
        *,
        predicate: Any = None,
    ) -> Any:
        deadline = time.time() + max(timeout_ms, 1) / 1000.0
        last_value = None
        check = predicate or bool
        while time.time() < deadline:
            try:
                last_value = self.client.execute(script, args or [])
            except Exception as exc:
                last_value = f"error: {exc}"
            if check(last_value):
                return last_value
            time.sleep(0.2)
        raise StepError(f"timed out waiting for {reason}; last_value={last_value!r}")

    def wait_for_js_true(self, script: str, timeout_ms: int, reason: str, args: list[Any] | None = None) -> None:
        self.wait_for_js_result(script, timeout_ms=timeout_ms, reason=reason, args=args)

    def wait(self, ms: int) -> None:
        time.sleep(max(ms, 0) / 1000.0)
        self.record("wait", ms=ms)

    def wait_for_selector(self, selector: str, timeout_ms: int) -> None:
        script = """
const selector = arguments[0];
return !!document.querySelector(selector);
"""
        self.wait_for_js_true(script, timeout_ms=timeout_ms, reason=f"selector {selector}", args=[selector])
        self.record("wait_for_selector", selector=selector, timeout_ms=timeout_ms)

    def wait_for_text(self, text: str, timeout_ms: int) -> None:
        script = """
const needle = arguments[0];
return (document.body && document.body.innerText || '').includes(needle);
"""
        self.wait_for_js_true(script, timeout_ms=timeout_ms, reason=f"text {text}", args=[text])
        self.record("wait_for_text", text=text, timeout_ms=timeout_ms)

    def _run_selector_step(
        self,
        *,
        selector: str,
        timeout_ms: int,
        action: str,
        script: str,
        args: list[Any],
        record: dict[str, Any],
    ) -> None:
        self.wait_for_selector(selector, timeout_ms)
        value = self.client.execute(script, args)
        if not isinstance(value, dict) or not value.get("ok"):
            raise StepError(f"{action} failed for {selector}: {value}")
        self.record(action, selector=selector, timeout_ms=timeout_ms, **record)

    def _click_selector(self, selector: str, timeout_ms: int, action: str, record: dict[str, Any]) -> None:
        self.wait_for_selector(selector, timeout_ms)
        fallback_error = None
        try:
            self.client.execute(
                "const el = document.querySelector(arguments[0]); if (el) el.scrollIntoView({block:'center', inline:'center'}); return !!el;",
                [selector],
            )
        except Exception:
            pass
        try:
            element = self.client.find_element_css(selector)
            self.client.click_element(element)
            self.record(action, selector=selector, timeout_ms=timeout_ms, click_mode="webdriver", **record)
            return
        except Exception as exc:
            fallback_error = str(exc)
        fallback_script = """
const selector = arguments[0];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
el.scrollIntoView({block:'center', inline:'center'});
el.click();
return {ok:true};
"""
        value = self.client.execute(fallback_script, [selector])
        if not isinstance(value, dict) or not value.get("ok"):
            raise StepError(f"{action} failed for {selector}: {value}")
        self.record(
            action,
            selector=selector,
            timeout_ms=timeout_ms,
            click_mode="js-fallback",
            fallback_error=fallback_error,
            **record,
        )

    def click(self, selector: str, timeout_ms: int) -> None:
        self._click_selector(selector, timeout_ms, "click", {})

    def click_text(self, text: str, timeout_ms: int, exact: bool = False) -> None:
        lookup_script = """
const needle = (arguments[0] || '').trim();
const exact = !!arguments[1];
const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
const selectorFor = (el) => {
  if (!el || !(el instanceof Element)) return '';
  const escapeCss = (value) => {
    if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
    return Array.from(String(value)).map((ch) => /[A-Za-z0-9_-]/.test(ch) ? ch : `\\${ch}`).join('');
  };
  if (el.id) return `#${escapeCss(el.id)}`;
  const parts = [];
  let node = el;
  while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (!parent) {
      parts.unshift(part);
      break;
    }
    const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
    if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
    parts.unshift(part);
    node = parent;
  }
  return parts.join(' > ');
};
const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"], summary'));
const texts = (el) => {
  const out = [
    normalize(el.innerText),
    normalize(el.textContent),
    normalize(el.getAttribute('aria-label')),
    normalize(el.getAttribute('title')),
    normalize(el.getAttribute('value')),
  ].filter(Boolean);
  if (el instanceof HTMLInputElement && el.labels) {
    for (const label of Array.from(el.labels)) out.push(normalize(label.innerText || label.textContent));
  }
  return out.filter(Boolean);
};
const matches = (value) => exact ? value === needle : value.includes(needle);
for (const el of candidates) {
  const values = texts(el);
  if (!values.some(matches)) continue;
  return {ok:true, selector: selectorFor(el), matched_text: values.find(matches) || ''};
}
return {ok:false, error:'text not found'};
"""
        value = self.wait_for_js_result(
            lookup_script,
            timeout_ms=timeout_ms,
            reason=f"text {text}",
            args=[text, exact],
            predicate=lambda result: isinstance(result, dict) and result.get("ok") and bool(result.get("selector")),
        )
        selector = str(value.get("selector") or "")
        if not selector:
            raise StepError(f"click_text failed for text {text}: {value}")
        self._click_selector(
            selector,
            timeout_ms,
            "click_text",
            {"text": text, "exact": exact, "matched_selector": selector, "matched_text": value.get("matched_text")},
        )

    def _type_selector(
        self,
        selector: str,
        text: str,
        timeout_ms: int,
        *,
        clear: bool,
        action: str,
        record: dict[str, Any],
    ) -> None:
        script = """
const selector = arguments[0];
const value = arguments[1];
const clear = !!arguments[2];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
el.scrollIntoView({block:'center', inline:'center'});
el.focus();
if (clear) {
  if ('value' in el) el.value = '';
  if (el.isContentEditable) el.textContent = '';
}
if ('value' in el) {
  el.value = value;
} else if (el.isContentEditable) {
  el.textContent = value;
} else {
  return {ok:false, error:'element is not writable'};
}
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true};
"""
        self._run_selector_step(
            selector=selector,
            timeout_ms=timeout_ms,
            action=action,
            script=script,
            args=[selector, text, clear],
            record={"text_length": len(text), "clear": clear, **record},
        )

    def type_text(self, selector: str, text: str, timeout_ms: int, clear: bool = True) -> None:
        self._type_selector(selector, text, timeout_ms, clear=clear, action="type", record={})

    def type_by_label(self, label: str, text: str, timeout_ms: int, clear: bool = True) -> None:
        lookup_script = """
const needle = (arguments[0] || '').trim();
const normalize = (input) => (input || '').replace(/\\s+/g, ' ').trim();
const matches = (input) => normalize(input).toLowerCase().includes(needle.toLowerCase());
const escapeCss = (value) => {
  if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
  return Array.from(String(value)).map((ch) => /[A-Za-z0-9_-]/.test(ch) ? ch : `\\${ch}`).join('');
};
const selectorFor = (el) => {
  if (!el || !(el instanceof Element)) return '';
  if (el.id) return `#${escapeCss(el.id)}`;
  const parts = [];
  let node = el;
  while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (!parent) {
      parts.unshift(part);
      break;
    }
    const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
    if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
    parts.unshift(part);
    node = parent;
  }
  return parts.join(' > ');
};
const writableSelector = 'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]), textarea, select, [contenteditable="true"]';
const findByLabel = () => {
  for (const labelEl of Array.from(document.querySelectorAll('label'))) {
    if (!matches(labelEl.innerText || labelEl.textContent || '')) continue;
    let target = null;
    const forId = labelEl.getAttribute('for');
    if (forId) target = document.getElementById(forId);
    if (!target) target = labelEl.querySelector(writableSelector);
    if (target) return target;
  }
  return null;
};
const directCandidates = Array.from(document.querySelectorAll(writableSelector));
const candidates = [
  findByLabel(),
  ...directCandidates.filter((el) => {
    const attrs = [el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('name'), el.getAttribute('id')];
    return attrs.some(matches);
  }),
].filter(Boolean);
for (const el of candidates) {
  return {ok:true, selector: selectorFor(el)};
}
return {ok:false, error:'label not found'};
"""
        value = self.wait_for_js_result(
            lookup_script,
            timeout_ms=timeout_ms,
            reason=f"label {label}",
            args=[label],
            predicate=lambda result: isinstance(result, dict) and result.get("ok") and bool(result.get("selector")),
        )
        selector = str(value.get("selector") or "")
        if not selector:
            raise StepError(f"type_by_label failed for label {label}: {value}")
        self._type_selector(
            selector,
            text,
            timeout_ms,
            clear=clear,
            action="type_by_label",
            record={"label": label, "matched_selector": selector},
        )

    def type_by_placeholder(self, placeholder: str, text: str, timeout_ms: int, clear: bool = True) -> None:
        lookup_script = """
const needle = (arguments[0] || '').trim().toLowerCase();
const escapeCss = (value) => {
  if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
  return Array.from(String(value)).map((ch) => /[A-Za-z0-9_-]/.test(ch) ? ch : `\\${ch}`).join('');
};
const selectorFor = (el) => {
  if (!el || !(el instanceof Element)) return '';
  if (el.id) return `#${escapeCss(el.id)}`;
  const parts = [];
  let node = el;
  while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (!parent) {
      parts.unshift(part);
      break;
    }
    const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
    if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
    parts.unshift(part);
    node = parent;
  }
  return parts.join(' > ');
};
const candidates = Array.from(document.querySelectorAll('input[placeholder], textarea[placeholder]'));
for (const el of candidates) {
  const currentPlaceholder = (el.getAttribute('placeholder') || '').trim().toLowerCase();
  if (!currentPlaceholder.includes(needle)) continue;
  return {ok:true, selector: selectorFor(el)};
}
return {ok:false, error:'placeholder not found'};
"""
        value = self.wait_for_js_result(
            lookup_script,
            timeout_ms=timeout_ms,
            reason=f"placeholder {placeholder}",
            args=[placeholder],
            predicate=lambda result: isinstance(result, dict) and result.get("ok") and bool(result.get("selector")),
        )
        selector = str(value.get("selector") or "")
        if not selector:
            raise StepError(f"type_by_placeholder failed for placeholder {placeholder}: {value}")
        self._type_selector(
            selector,
            text,
            timeout_ms,
            clear=clear,
            action="type_by_placeholder",
            record={"placeholder": placeholder, "matched_selector": selector},
        )

    def _submit_selector(self, selector: str, timeout_ms: int, *, action: str, record: dict[str, Any]) -> None:
        script = """
const selector = arguments[0];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
const form = el.matches('form') ? el : el.closest('form');
if (!form) return {ok:false, error:'no parent form'};
form.scrollIntoView({block:'center', inline:'center'});
if (typeof form.requestSubmit === 'function') {
  form.requestSubmit();
} else {
  form.submit();
}
return {ok:true};
"""
        self._run_selector_step(
            selector=selector,
            timeout_ms=timeout_ms,
            action=action,
            script=script,
            args=[selector],
            record=record,
        )

    def submit(self, selector: str, timeout_ms: int) -> None:
        self._submit_selector(selector, timeout_ms, action="submit", record={})

    def submit_first_form(self, timeout_ms: int) -> None:
        self._submit_selector("form", timeout_ms, action="submit_first_form", record={"matched_selector": "form"})

    def snapshot_dom(self, path: str) -> None:
        dest = self.output_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.client.page_source(), encoding="utf-8")
        self.record("dump_dom", path=str(dest.relative_to(self.output_dir)))

    def snapshot_png(self, path: str) -> None:
        dest = self.output_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.client.screenshot())
        self.record("screenshot", path=str(dest.relative_to(self.output_dir)))

    def execute_step(self, raw_step: dict[str, Any]) -> None:
        action = str(raw_step.get("action") or "").strip().lower()
        timeout_ms = int(raw_step.get("timeout_ms") or raw_step.get("timeoutMs") or 10000)
        if action == "wait":
            self.wait(int(raw_step.get("ms") or raw_step.get("wait_ms") or raw_step.get("waitMs") or 1000))
            return
        if action == "wait_for_selector":
            self.wait_for_selector(str(raw_step["selector"]), timeout_ms)
            return
        if action == "wait_for_text":
            self.wait_for_text(str(raw_step["text"]), timeout_ms)
            return
        if action == "click":
            self.click(str(raw_step["selector"]), timeout_ms)
            return
        if action == "click_text":
            self.click_text(
                str(raw_step["text"]),
                timeout_ms,
                exact=bool(raw_step.get("exact", False)),
            )
            return
        if action == "type":
            self.type_text(
                str(raw_step["selector"]),
                str(raw_step.get("text") or ""),
                timeout_ms,
                clear=bool(raw_step.get("clear", True)),
            )
            return
        if action == "type_by_label":
            self.type_by_label(
                str(raw_step["label"]),
                str(raw_step.get("text") or ""),
                timeout_ms,
                clear=bool(raw_step.get("clear", True)),
            )
            return
        if action == "type_by_placeholder":
            self.type_by_placeholder(
                str(raw_step["placeholder"]),
                str(raw_step.get("text") or ""),
                timeout_ms,
                clear=bool(raw_step.get("clear", True)),
            )
            return
        if action == "submit":
            self.submit(str(raw_step["selector"]), timeout_ms)
            return
        if action == "submit_first_form":
            self.submit_first_form(timeout_ms)
            return
        if action == "dump_dom":
            self.snapshot_dom(str(raw_step.get("path") or "dom.html"))
            return
        if action == "screenshot":
            self.snapshot_png(str(raw_step.get("path") or "screenshot.png"))
            return
        raise StepError(f"unsupported step action: {action}")

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def find_binary(candidates: list[str]) -> str | None:
    for item in candidates:
        if not item:
            continue
        resolved = shutil.which(item) if os.path.sep not in item else item
        if resolved and Path(resolved).exists():
            return resolved
    return None


def load_steps(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if isinstance(payload, dict):
        payload = payload.get("steps") or []
    if not isinstance(payload, list):
        raise RuntimeError("steps file must be a JSON list or {\"steps\": [...]} object")
    normalized = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"step {idx} is not an object")
        normalized.append(item)
    return normalized


def parse_cookie_arg(raw: str, url: str) -> dict[str, Any]:
    if "=" not in raw:
        raise RuntimeError(f"cookie must use name=value syntax: {raw}")
    name, value = raw.split("=", 1)
    parsed = urllib.parse.urlparse(url)
    return {
        "name": name,
        "value": value,
        "domain": parsed.hostname or "",
        "path": "/",
    }


def load_auth_cookies(path: str | None, url: str) -> list[dict[str, Any]]:
    if not path:
        return []
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cookies_obj = payload.get("cookies") or {}
    if not isinstance(cookies_obj, dict):
        return []
    out = []
    for name, value in cookies_obj.items():
        if value is None:
            continue
        out.append({"name": str(name), "value": str(value), "domain": hostname, "path": "/"})
    return out


def wait_for_driver_ready(base_url: str, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/status", timeout=2) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            value = unwrap_value(parsed)
            if isinstance(value, dict) and value.get("ready"):
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"chromedriver did not become ready: {last_error}")


def start_chromedriver(chromedriver_bin: str, port: int) -> subprocess.Popen[str]:
    cmd = [chromedriver_bin, f"--port={port}", "--allowed-origins=*", "--allowed-ips="]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded Chromium-based live route or page-action flow against an exact in-scope URL."
    )
    parser.add_argument("--url", required=True, help="Exact URL to open, including fragment route when applicable.")
    parser.add_argument("--output-dir", required=True, help="Directory for screenshots, DOM dumps, and summary.json.")
    parser.add_argument("--steps-file", help="JSON file containing browser steps (list or {steps:[...]}).")
    parser.add_argument("--cookie", action="append", default=[], help="Cookie to inject as name=value (repeatable).")
    parser.add_argument("--cookies-from-auth", help="Read cookies from engagement auth.json and inject them for the target origin.")
    parser.add_argument("--wait-ms", type=int, default=1500, help="Initial settle time after navigation (default: 1500).")
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Ready-state timeout after each navigation (default: 15000).")
    parser.add_argument("--dom-file", default="dom.html", help="Default DOM snapshot path relative to output-dir.")
    parser.add_argument("--screenshot", default="screenshot.png", help="Default screenshot path relative to output-dir.")
    parser.add_argument("--summary-json", default="summary.json", help="Summary JSON path relative to output-dir.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    steps = load_steps(args.steps_file)

    chrome_bin = find_binary([
        os.environ.get("CHROME_BIN", ""),
        os.environ.get("KATANA_CHROME_BIN", ""),
        "/usr/bin/chromium",
        "chromium",
        "chromium-browser",
        "google-chrome",
        "chrome",
    ])
    chromedriver_bin = find_binary([
        os.environ.get("CHROMEDRIVER_BIN", ""),
        "/usr/bin/chromedriver",
        "chromedriver",
    ])
    if not chromedriver_bin:
        raise RuntimeError("chromedriver not found; set CHROMEDRIVER_BIN or install chromium-driver")

    driver_port = find_free_port()
    base_url = f"http://127.0.0.1:{driver_port}"
    log_path = output_dir / "chromedriver.log"
    session_tmpdir = Path(tempfile.mkdtemp(prefix="browser-flow-profile-"))
    proc = start_chromedriver(chromedriver_bin, driver_port)
    client = WebDriverClient(base_url)
    flow = BrowserFlow(client, output_dir)

    cookies = [parse_cookie_arg(item, args.url) for item in args.cookie]
    cookies.extend(load_auth_cookies(args.cookies_from_auth, args.url))

    summary: dict[str, Any] = {
        "url": args.url,
        "chrome_binary": chrome_bin,
        "chromedriver_binary": chromedriver_bin,
        "cookies_applied": len(cookies),
        "steps_requested": len(steps),
    }

    try:
        wait_for_driver_ready(base_url)
        client.create_session(chrome_bin, session_tmpdir)

        parsed_target = urllib.parse.urlparse(args.url)
        origin = urllib.parse.urlunparse((parsed_target.scheme, parsed_target.netloc, "/", "", "", ""))
        if cookies:
            client.navigate(origin)
            flow.wait_for_document(args.timeout_ms)
            for cookie in cookies:
                client.add_cookie(cookie)

        client.navigate(args.url)
        flow.wait_for_document(args.timeout_ms)
        if args.wait_ms > 0:
            flow.wait(args.wait_ms)

        if steps:
            for step in steps:
                flow.execute_step(step)
        else:
            flow.snapshot_dom(args.dom_file)
            flow.snapshot_png(args.screenshot)

        if steps:
            default_dom = output_dir / args.dom_file
            default_png = output_dir / args.screenshot
            if not default_dom.exists():
                flow.snapshot_dom(args.dom_file)
            if not default_png.exists():
                flow.snapshot_png(args.screenshot)

        summary.update(
            {
                "status": "ok",
                "title": client.title(),
                "final_url": client.current_url(),
                "steps_run": flow.steps_run,
                "dom_file": args.dom_file,
                "screenshot": args.screenshot,
            }
        )
        write_json(output_dir / args.summary_json, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        summary.update(
            {
                "status": "error",
                "error": str(exc),
                "steps_run": flow.steps_run,
            }
        )
        write_json(output_dir / args.summary_json, summary)
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        client.close()
        stdout_data = ""
        if proc.poll() is None:
            proc.terminate()
            try:
                stdout_data, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_data, _ = proc.communicate(timeout=5)
        else:
            try:
                stdout_data, _ = proc.communicate(timeout=1)
            except Exception:
                stdout_data = ""
        try:
            log_path.write_text(stdout_data or "", encoding="utf-8")
        except Exception:
            pass
        shutil.rmtree(session_tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
