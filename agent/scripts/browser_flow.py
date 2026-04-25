#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import shutil
from html import unescape
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


def unwrap_value(payload: Any) -> Any:
    if isinstance(payload, dict) and "value" in payload:
        return payload["value"]
    return payload


ELEMENT_REFERENCE_KEYS = ("element-6066-11e4-a52e-4f735466cecf", "ELEMENT")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def strip_html(fragment: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return normalize_text(cleaned)


def unique_nonempty(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        normalized = normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(normalized)
        if len(kept) >= limit:
            break
    return kept


_INTERESTING_ASSET_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
)

_NOISY_ROUTE_EXTENSIONS = (
    ".js",
    ".css",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)


def normalize_dom_reference(value: str | None) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    lower = normalized.lower()
    if lower.startswith(("javascript:", "mailto:", "tel:", "data:", "blob:")):
        return None
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc:
        return None
    if not (parsed.path or parsed.query or parsed.fragment):
        return None
    if not normalized.startswith(("#", "/", "./", "../")) and not parsed.path:
        return None
    return normalized


def is_interesting_asset_reference(reference: str) -> bool:
    parsed = urllib.parse.urlsplit(reference)
    candidate = (parsed.path or parsed.fragment or "").lower()
    return any(candidate.endswith(ext) for ext in _INTERESTING_ASSET_EXTENSIONS)


def is_route_hint_reference(reference: str) -> bool:
    if is_interesting_asset_reference(reference):
        return False
    parsed = urllib.parse.urlsplit(reference)
    candidate = (parsed.path or parsed.fragment or "").lower()
    if any(candidate.endswith(ext) for ext in _NOISY_ROUTE_EXTENSIONS):
        return False
    return True


def extract_dom_references(body_html: str, attr_patterns: list[str], predicate: Callable[[str], bool], limit: int) -> list[str]:
    refs: list[str] = []
    for pattern in attr_patterns:
        for match in re.finditer(pattern, body_html):
            reference = normalize_dom_reference(match.group(2))
            if reference and predicate(reference):
                refs.append(reference)
    return unique_nonempty(refs, limit)


def summarize_dom_html(html: str) -> dict[str, Any]:
    body_match = re.search(r"(?is)<body[^>]*>(.*?)</body>", html)
    body_html = body_match.group(1) if body_match else html
    headings = unique_nonempty(
        [strip_html(match.group(1)) for match in re.finditer(r"(?is)<h[1-3][^>]*>(.*?)</h[1-3]>", body_html)],
        8,
    )
    buttons = unique_nonempty(
        [strip_html(match.group(1)) for match in re.finditer(r"(?is)<button[^>]*>(.*?)</button>", body_html)]
        + [match.group(1) for match in re.finditer(r"(?is)<input[^>]+type=[\"'](?:submit|button)[\"'][^>]*value=[\"'](.*?)[\"']", body_html)],
        10,
    )
    labels = unique_nonempty(
        [strip_html(match.group(1)) for match in re.finditer(r"(?is)<label[^>]*>(.*?)</label>", body_html)],
        10,
    )
    placeholders = unique_nonempty(
        [match.group(3) for match in re.finditer(r"(?is)\b(placeholder)=([\"'])(.*?)\2", body_html)],
        10,
    )
    links = unique_nonempty(
        [strip_html(match.group(1)) for match in re.finditer(r"(?is)<a[^>]*>(.*?)</a>", body_html)],
        10,
    )
    route_hints = extract_dom_references(
        body_html,
        [
            r"(?is)\b(?:href|routerlink|action)=([\"'])(.*?)\1",
            r"(?is)\bformaction=([\"'])(.*?)\1",
        ],
        is_route_hint_reference,
        12,
    )
    asset_hints = extract_dom_references(
        body_html,
        [
            r"(?is)\b(?:src|poster|data-src|href)=([\"'])(.*?)\1",
            r"(?is)\bsrcset=([\"'])(.*?)\1",
        ],
        is_interesting_asset_reference,
        10,
    )
    inputs: list[dict[str, str]] = []
    seen_inputs: set[tuple[str, str, str, str]] = set()
    for match in re.finditer(r"(?is)<input\b([^>]*)>", body_html):
        attrs = match.group(1)
        input_type = normalize_text(next((m.group(2) for m in re.finditer(r"(?is)\btype=([\"'])(.*?)\1", attrs)), "text")) or "text"
        name = normalize_text(next((m.group(2) for m in re.finditer(r"(?is)\bname=([\"'])(.*?)\1", attrs)), ""))
        element_id = normalize_text(next((m.group(2) for m in re.finditer(r"(?is)\bid=([\"'])(.*?)\1", attrs)), ""))
        placeholder = normalize_text(next((m.group(2) for m in re.finditer(r"(?is)\bplaceholder=([\"'])(.*?)\1", attrs)), ""))
        signature = (input_type, name, element_id, placeholder)
        if signature in seen_inputs:
            continue
        seen_inputs.add(signature)
        inputs.append(
            {
                "type": input_type,
                "name": name,
                "id": element_id,
                "placeholder": placeholder,
            }
        )
        if len(inputs) >= 8:
            break
    page_text_preview = strip_html(body_html)[:400]
    return {
        "heading_count": len(headings),
        "form_count": len(re.findall(r"(?is)<form\b", body_html)),
        "headings": headings,
        "buttons": buttons,
        "labels": labels,
        "placeholders": placeholders,
        "links": links,
        "route_hints": route_hints,
        "asset_hints": asset_hints,
        "inputs": inputs,
        "page_text_preview": page_text_preview,
    }


def summarize_dom_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    summary = summarize_dom_html(html)
    summary["path"] = str(path.name)
    return summary


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

    def alert_text(self) -> str:
        return str(self._request("GET", f"/session/{self.session_id}/alert/text"))

    def accept_alert(self) -> None:
        self._request("POST", f"/session/{self.session_id}/alert/accept", {})

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

    def send_keys_element(self, element: Any, text: str) -> None:
        element_ref = urllib.parse.quote(extract_element_reference(element), safe="")
        self._request(
            "POST",
            f"/session/{self.session_id}/element/{element_ref}/value",
            {"text": text, "value": list(text)},
        )


class StepError(RuntimeError):
    pass


class BrowserFlow:
    def __init__(self, client: WebDriverClient, output_dir: Path):
        self.client = client
        self.output_dir = output_dir
        self.steps_run: list[dict[str, Any]] = []
        self.observed_alerts: list[str] = []

    def record(self, action: str, **extra: Any) -> None:
        item = {"action": action}
        item.update(extra)
        self.steps_run.append(item)

    def _parse_alert_text(self, message: str) -> str:
        match = re.search(r"Alert text\s*:\s*(.+?)(?:\\n|$)", message, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _recover_unexpected_alert(self, exc: Exception, source_action: str) -> bool:
        message = str(exc)
        if "unexpected alert open" not in message.lower():
            return False

        alert_text = ""
        if self.client is not None and hasattr(self.client, "alert_text"):
            try:
                alert_text = str(self.client.alert_text() or "").strip()
            except Exception:
                alert_text = ""
        if not alert_text:
            alert_text = self._parse_alert_text(message) or "<unknown>"

        accepted = False
        if self.client is not None and hasattr(self.client, "accept_alert"):
            try:
                self.client.accept_alert()
                accepted = True
            except Exception:
                accepted = False

        self.observed_alerts.append(alert_text)
        self.record("unexpected_alert", source_action=source_action, text=alert_text, accepted=accepted)
        return True

    def call_with_alert_recovery(self, fn: Any, *, source_action: str) -> Any:
        try:
            return fn()
        except Exception as exc:
            if not self._recover_unexpected_alert(exc, source_action):
                raise
        return fn()

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
                last_value = self.call_with_alert_recovery(
                    lambda: self.client.execute(script, args or []),
                    source_action=f"wait_for_js:{reason}",
                )
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
        value = self.call_with_alert_recovery(
            lambda: self.client.execute(script, args),
            source_action=action,
        )
        if not isinstance(value, dict) or not value.get("ok"):
            raise StepError(f"{action} failed for {selector}: {value}")
        self.record(action, selector=selector, timeout_ms=timeout_ms, **record)

    def dismiss_common_overlays(self, timeout_ms: int, *, source_action: str = "") -> None:
        script = r"""
const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
const labelFor = (el) => normalize(
  el.getAttribute?.('aria-label') ||
  el.getAttribute?.('title') ||
  el.innerText ||
  el.textContent ||
  el.className ||
  el.id ||
  el.tagName ||
  ''
);
const overlayKeywords = ['cookie', 'consent', 'welcome', 'overlay', 'backdrop', 'drawer', 'modal', 'dialog', 'banner', 'tour', 'intro'];
const dismissKeywords = ['dismiss', 'accept', 'accept all', 'allow all', 'got it', 'not interested', 'close welcome banner', 'skip'];
const dismissed = [];
const seen = new Set();
const clickIt = (el, kind) => {
  if (!el || seen.has(el) || !visible(el)) return;
  seen.add(el);
  try { el.scrollIntoView({block:'center', inline:'center'}); } catch (_err) {}
  try {
    el.click();
    dismissed.push({kind, label: labelFor(el)});
  } catch (_err) {}
};

for (const el of Array.from(document.querySelectorAll('*'))) {
  if (!visible(el)) continue;
  const cls = normalize(typeof el.className === 'string' ? el.className : '');
  if (cls.includes('backdrop') || cls.includes('overlay-backdrop') || cls.includes('drawer-backdrop')) {
    clickIt(el, 'backdrop');
  }
}

const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
for (const el of candidates) {
  if (!visible(el)) continue;
  const texts = [
    normalize(el.innerText),
    normalize(el.textContent),
    normalize(el.getAttribute('aria-label')),
    normalize(el.getAttribute('title')),
    normalize(el.getAttribute('value')),
  ].filter(Boolean);
  if (!texts.length) continue;
  let node = el;
  let overlayContext = false;
  while (node && node !== document.documentElement) {
    const haystack = normalize(
      (typeof node.className === 'string' ? node.className : '') + ' ' +
      (node.getAttribute?.('aria-label') || '') + ' ' +
      (node.getAttribute?.('role') || '')
    );
    if (overlayKeywords.some((keyword) => haystack.includes(keyword))) {
      overlayContext = true;
      break;
    }
    node = node.parentElement;
  }
  const keywordHit = texts.some((text) => dismissKeywords.some((keyword) => text.includes(keyword)));
  const overlayHit = texts.some((text) => overlayKeywords.some((keyword) => text.includes(keyword)));
  if (keywordHit && (overlayContext || overlayHit)) {
    clickIt(el, 'control');
  }
}

return {ok:true, dismissed};
"""
        value = self.call_with_alert_recovery(
            lambda: self.client.execute(script, []),
            source_action=source_action or "dismiss_common_overlays",
        )
        if not isinstance(value, dict) or not value.get("ok"):
            raise StepError(f"dismiss_common_overlays failed: {value}")
        dismissed = value.get("dismissed") or []
        labels = [str(item.get("label") or "") for item in dismissed if isinstance(item, dict)]
        self.record(
            "dismiss_common_overlays",
            timeout_ms=timeout_ms,
            source_action=source_action,
            dismissed_count=len(dismissed),
            dismissed_labels=labels,
        )

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
        value = self.call_with_alert_recovery(
            lambda: self.client.execute(fallback_script, [selector]),
            source_action=action,
        )
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
const tagName = (el.tagName || '').toLowerCase();
const inputType = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
if (tagName === 'input' && inputType === 'file') {
  return {ok:false, error:'file inputs require upload action'};
}
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

    def _resolve_selector_by_label(self, label: str, timeout_ms: int, *, field_selector: str, action: str) -> str:
        lookup_script = """
const needle = (arguments[0] || '').trim();
const fieldSelector = arguments[1] || 'input, textarea, select';
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
const findByLabel = () => {
  for (const labelEl of Array.from(document.querySelectorAll('label'))) {
    if (!matches(labelEl.innerText || labelEl.textContent || '')) continue;
    let target = null;
    const forId = labelEl.getAttribute('for');
    if (forId) target = document.getElementById(forId);
    if (!target) target = labelEl.querySelector(fieldSelector);
    if (!target) {
      let current = labelEl.parentElement;
      while (current && !target) {
        target = current.querySelector(fieldSelector);
        current = current.parentElement;
      }
    }
    if (target) return target;
  }
  return null;
};
const directCandidates = Array.from(document.querySelectorAll(fieldSelector));
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
            args=[label, field_selector],
            predicate=lambda result: isinstance(result, dict) and result.get("ok") and bool(result.get("selector")),
        )
        selector = str(value.get("selector") or "")
        if not selector:
            raise StepError(f"{action} failed for label {label}: {value}")
        return selector

    def type_by_label(self, label: str, text: str, timeout_ms: int, clear: bool = True) -> None:
        selector = self._resolve_selector_by_label(
            label,
            timeout_ms,
            field_selector='input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]), textarea, select, [contenteditable="true"]',
            action="type_by_label",
        )
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

    def set_range_value(self, selector: str, value: Any, timeout_ms: int, *, action: str = "set_range") -> None:
        script = """
const selector = arguments[0];
const requested = arguments[1];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
el.scrollIntoView({block:'center', inline:'center'});
el.focus();
const tagName = (el.tagName || '').toLowerCase();
const inputType = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
if (tagName !== 'input' || (inputType !== 'range' && inputType !== 'number')) {
  return {ok:false, error:'element is not range/number input'};
}
const serialized = String(requested ?? '');
if (!serialized.trim()) {
  return {ok:false, error:'value is empty'};
}
const numeric = Number(serialized);
if (!Number.isFinite(numeric)) {
  return {ok:false, error:'value is not numeric'};
}
const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
if (nativeSetter && typeof nativeSetter.set === 'function') {
  nativeSetter.set.call(el, serialized);
} else {
  el.value = serialized;
}
try {
  el.dispatchEvent(new InputEvent('input', {bubbles:true, data: serialized, inputType: 'insertText'}));
} catch (_err) {
  el.dispatchEvent(new Event('input', {bubbles:true}));
}
el.dispatchEvent(new Event('change', {bubbles:true}));
el.dispatchEvent(new Event('mouseup', {bubbles:true}));
el.dispatchEvent(new Event('blur', {bubbles:true}));
return {
  ok:true,
  requested: serialized,
  effective: String(el.value ?? ''),
  min: el.getAttribute('min') || '',
  max: el.getAttribute('max') || '',
  step: el.getAttribute('step') || '',
  type: inputType,
};
"""
        self.wait_for_selector(selector, timeout_ms)
        value_record = self.call_with_alert_recovery(
            lambda: self.client.execute(script, [selector, value]),
            source_action=action,
        )
        if not isinstance(value_record, dict) or not value_record.get("ok"):
            raise StepError(f"{action} failed for {selector}: {value_record}")
        self.record(
            action,
            selector=selector,
            timeout_ms=timeout_ms,
            requested_value=str(value_record.get("requested") or ""),
            effective_value=str(value_record.get("effective") or ""),
            min=str(value_record.get("min") or ""),
            max=str(value_record.get("max") or ""),
            step=str(value_record.get("step") or ""),
            input_type=str(value_record.get("type") or ""),
        )

    def select_option(
        self,
        selector: str,
        timeout_ms: int,
        *,
        value: Any = None,
        text: Any = None,
        index: Any = None,
        action: str = "select_option",
        record: dict[str, Any] | None = None,
    ) -> None:
        script = """
const selector = arguments[0];
const requestedValue = arguments[1];
const requestedText = arguments[2];
const requestedIndex = arguments[3];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
el.scrollIntoView({block:'center', inline:'center'});
el.focus();
if ((el.tagName || '').toLowerCase() !== 'select') {
  return {ok:false, error:'element is not select'};
}
const normalize = (input) => String(input ?? '').replace(/\\s+/g, ' ').trim().toLowerCase();
const options = Array.from(el.options || []);
let targetIndex = -1;
let mode = '';
if (requestedIndex !== null && requestedIndex !== undefined && String(requestedIndex).trim() !== '') {
  const numericIndex = Number(requestedIndex);
  if (Number.isInteger(numericIndex) && numericIndex >= 0 && numericIndex < options.length) {
    targetIndex = numericIndex;
    mode = 'index';
  }
}
if (targetIndex === -1 && requestedValue !== null && requestedValue !== undefined && String(requestedValue).trim() !== '') {
  const rawValue = String(requestedValue);
  targetIndex = options.findIndex((option) => String(option.value ?? '') === rawValue);
  if (targetIndex !== -1) mode = 'value';
}
if (targetIndex === -1 && requestedText !== null && requestedText !== undefined && String(requestedText).trim() !== '') {
  const normalizedText = normalize(requestedText);
  targetIndex = options.findIndex((option) => normalize(option.textContent || option.innerText || '') === normalizedText);
  if (targetIndex !== -1) mode = 'text';
}
if (targetIndex === -1) {
  return {
    ok:false,
    error:'option not found',
    available_options: options.map((option, idx) => ({index: idx, value: String(option.value ?? ''), text: String((option.textContent || option.innerText || '').trim())})),
  };
}
el.selectedIndex = targetIndex;
el.value = options[targetIndex].value;
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new Event('change', {bubbles:true}));
el.dispatchEvent(new Event('blur', {bubbles:true}));
const selected = options[el.selectedIndex] || null;
return {
  ok:true,
  requested_value: requestedValue === null || requestedValue === undefined ? '' : String(requestedValue),
  requested_text: requestedText === null || requestedText === undefined ? '' : String(requestedText),
  requested_index: requestedIndex === null || requestedIndex === undefined ? '' : String(requestedIndex),
  effective_index: String(el.selectedIndex),
  effective_value: selected ? String(selected.value ?? '') : '',
  effective_text: selected ? String((selected.textContent || selected.innerText || '').trim()) : '',
  option_count: options.length,
  mode,
};
"""
        self.wait_for_selector(selector, timeout_ms)
        value_record = self.call_with_alert_recovery(
            lambda: self.client.execute(script, [selector, value, text, index]),
            source_action=action,
        )
        if not isinstance(value_record, dict) or not value_record.get("ok"):
            raise StepError(f"{action} failed for {selector}: {value_record}")
        payload = record or {}
        self.record(
            action,
            selector=selector,
            timeout_ms=timeout_ms,
            requested_value=str(value_record.get("requested_value") or ""),
            requested_text=str(value_record.get("requested_text") or ""),
            requested_index=str(value_record.get("requested_index") or ""),
            effective_value=str(value_record.get("effective_value") or ""),
            effective_text=str(value_record.get("effective_text") or ""),
            effective_index=str(value_record.get("effective_index") or ""),
            option_count=int(value_record.get("option_count") or 0),
            match_mode=str(value_record.get("mode") or ""),
            **payload,
        )

    def select_by_label(
        self,
        label: str,
        timeout_ms: int,
        *,
        value: Any = None,
        text: Any = None,
        index: Any = None,
        action: str = "select_by_label",
    ) -> None:
        selector = self._resolve_selector_by_label(
            label,
            timeout_ms,
            field_selector="select",
            action=action,
        )
        self.select_option(
            selector,
            timeout_ms,
            value=value,
            text=text,
            index=index,
            action=action,
            record={"label": label, "matched_selector": selector},
        )

    def _normalize_upload_paths(self, raw_paths: Any) -> list[Path]:
        if isinstance(raw_paths, (str, os.PathLike)):
            candidates = [raw_paths]
        elif isinstance(raw_paths, list):
            candidates = raw_paths
        else:
            raise StepError(f"upload requires path/file/paths, got: {raw_paths!r}")

        resolved: list[Path] = []
        for candidate in candidates:
            path_text = str(candidate or "").strip()
            if not path_text:
                continue
            path = Path(path_text).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if not path.exists() or not path.is_file():
                raise StepError(f"upload file does not exist: {path}")
            resolved.append(path)

        if not resolved:
            raise StepError("upload requires at least one existing file path")
        return resolved

    def upload_file(self, selector: str, raw_paths: Any, timeout_ms: int) -> None:
        paths = self._normalize_upload_paths(raw_paths)
        self.wait_for_selector(selector, timeout_ms)
        inspect_script = """
const selector = arguments[0];
const el = document.querySelector(selector);
if (!el) return {ok:false, error:'selector not found'};
el.scrollIntoView({block:'center', inline:'center'});
const tag = (el.tagName || '').toLowerCase();
const type = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
return {ok:true, tag, type, multiple: !!el.multiple, is_file: tag === 'input' && type === 'file'};
"""
        value = self.call_with_alert_recovery(
            lambda: self.client.execute(inspect_script, [selector]),
            source_action="upload",
        )
        if not isinstance(value, dict) or not value.get("ok"):
            raise StepError(f"upload failed for {selector}: {value}")
        if not value.get("is_file"):
            raise StepError(f"upload target is not an input[type=file]: {selector}")

        upload_text = "\n".join(str(path) for path in paths)
        try:
            element = self.client.find_element_css(selector)
            self.client.send_keys_element(element, upload_text)
        except Exception as exc:
            raise StepError(f"upload failed for {selector}: {exc}") from exc

        self.record(
            "upload",
            selector=selector,
            timeout_ms=timeout_ms,
            file_count=len(paths),
            files=[path.name for path in paths],
            multiple=bool(value.get("multiple")),
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
        dom = self.call_with_alert_recovery(self.client.page_source, source_action="page_source")
        dest.write_text(dom, encoding="utf-8")
        self.record("dump_dom", path=str(dest.relative_to(self.output_dir)))

    def snapshot_png(self, path: str) -> None:
        dest = self.output_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        screenshot = self.call_with_alert_recovery(self.client.screenshot, source_action="screenshot")
        dest.write_bytes(screenshot)
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
        if action in {"click", "click_text", "type", "type_by_label", "type_by_placeholder", "set_range", "set_rating", "select", "select_option", "choose_option", "select_by_label", "upload", "submit", "submit_first_form"}:
            self.dismiss_common_overlays(timeout_ms, source_action=action)
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
        if action in {"set_range", "set_rating"}:
            raw_value = raw_step.get("value")
            if raw_value is None:
                raw_value = raw_step.get("rating")
            if raw_value is None:
                raw_value = raw_step.get("text")
            self.set_range_value(
                str(raw_step["selector"]),
                raw_value,
                timeout_ms,
                action=action,
            )
            return
        if action in {"select", "select_option", "choose_option"}:
            self.select_option(
                str(raw_step["selector"]),
                timeout_ms,
                value=raw_step.get("value"),
                text=raw_step.get("text") or raw_step.get("option_text") or raw_step.get("label_text"),
                index=raw_step.get("index"),
                action=action,
            )
            return
        if action == "select_by_label":
            self.select_by_label(
                str(raw_step["label"]),
                timeout_ms,
                value=raw_step.get("value"),
                text=raw_step.get("text") or raw_step.get("option_text"),
                index=raw_step.get("index"),
                action=action,
            )
            return
        if action == "upload":
            upload_paths = raw_step.get("paths")
            if upload_paths is None:
                upload_paths = raw_step.get("path") or raw_step.get("file") or raw_step.get("file_path") or raw_step.get("filePath")
            self.upload_file(
                str(raw_step["selector"]),
                upload_paths,
                timeout_ms,
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


def load_auth_payload(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def stringify_storage_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_storage_entries(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        normalized = stringify_storage_value(value)
        if normalized is None:
            continue
        out[str(key)] = normalized
    return out


def extract_bearer_token(headers: Any) -> str | None:
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).lower() != "authorization" or value is None:
            continue
        raw = str(value).strip()
        if raw.lower().startswith("bearer ") and len(raw) > 7:
            return raw[7:].strip()
    return None


def load_auth_cookies(path: str | None, url: str) -> list[dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    payload = load_auth_payload(path)
    cookies_obj = payload.get("cookies") or {}
    if not isinstance(cookies_obj, dict):
        return []
    out = []
    for name, value in cookies_obj.items():
        if value is None:
            continue
        out.append({"name": str(name), "value": str(value), "domain": hostname, "path": "/"})
    return out


def load_auth_storage(path: str | None) -> dict[str, dict[str, str]]:
    payload = load_auth_payload(path)
    local_storage: dict[str, str] = {}
    session_storage: dict[str, str] = {}

    explicit_storage = payload.get("browser_storage") or payload.get("storage") or {}
    if isinstance(explicit_storage, dict):
        local_storage.update(
            normalize_storage_entries(
                explicit_storage.get("localStorage") or explicit_storage.get("local_storage") or {}
            )
        )
        session_storage.update(
            normalize_storage_entries(
                explicit_storage.get("sessionStorage") or explicit_storage.get("session_storage") or {}
            )
        )

    tokens = payload.get("tokens") or {}
    if isinstance(tokens, dict):
        for key, value in tokens.items():
            normalized = stringify_storage_value(value)
            if normalized is None:
                continue
            key_str = str(key)
            lowered = key_str.lower()
            if lowered in {"bid", "basketid", "basket_id", "cartid", "cart_id", "sessionid", "session_id"}:
                session_storage.setdefault(key_str, normalized)
                session_storage.setdefault("bid", normalized)
                continue
            if lowered in {"token", "jwt", "access_token", "accesstoken", "id_token", "idtoken", "bearer", "bearer_token"}:
                local_storage.setdefault(key_str, normalized)
                local_storage.setdefault("token", normalized)

    bearer = extract_bearer_token(payload.get("headers") or {})
    if bearer:
        local_storage.setdefault("token", bearer)

    return {
        "localStorage": local_storage,
        "sessionStorage": session_storage,
    }


def apply_auth_storage(client: WebDriverClient, storage_state: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    local_items = normalize_storage_entries(storage_state.get("localStorage") or {})
    session_items = normalize_storage_entries(storage_state.get("sessionStorage") or {})
    if not local_items and not session_items:
        return {"localStorage": [], "sessionStorage": []}
    script = """
const localItems = arguments[0] || {};
const sessionItems = arguments[1] || {};
const apply = (store, items) => {
  const applied = [];
  for (const [key, value] of Object.entries(items)) {
    store.setItem(String(key), String(value));
    applied.push(String(key));
  }
  return applied;
};
return {
  localStorage: apply(window.localStorage, localItems),
  sessionStorage: apply(window.sessionStorage, sessionItems),
};
"""
    value = client.execute(script, [local_items, session_items])
    if not isinstance(value, dict):
        raise RuntimeError(f"failed to apply auth storage state: {value!r}")
    return {
        "localStorage": [str(item) for item in value.get("localStorage") or []],
        "sessionStorage": [str(item) for item in value.get("sessionStorage") or []],
    }


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
    storage_state = load_auth_storage(args.cookies_from_auth)
    requested_storage = {
        "localStorage": sorted((storage_state.get("localStorage") or {}).keys()),
        "sessionStorage": sorted((storage_state.get("sessionStorage") or {}).keys()),
    }

    summary: dict[str, Any] = {
        "url": args.url,
        "chrome_binary": chrome_bin,
        "chromedriver_binary": chromedriver_bin,
        "cookies_applied": len(cookies),
        "steps_requested": len(steps),
        "storage_requested": requested_storage,
        "storage_injected": False,
        "storage_applied": {"localStorage": [], "sessionStorage": []},
    }

    try:
        wait_for_driver_ready(base_url)
        client.create_session(chrome_bin, session_tmpdir)

        parsed_target = urllib.parse.urlparse(args.url)
        origin = urllib.parse.urlunparse((parsed_target.scheme, parsed_target.netloc, "/", "", "", ""))
        if cookies or requested_storage["localStorage"] or requested_storage["sessionStorage"]:
            client.navigate(origin)
            flow.wait_for_document(args.timeout_ms)
            for cookie in cookies:
                client.add_cookie(cookie)
            applied_storage = apply_auth_storage(client, storage_state)
            summary["storage_applied"] = applied_storage
            summary["storage_injected"] = bool(applied_storage["localStorage"] or applied_storage["sessionStorage"])

        client.navigate(args.url)
        flow.wait_for_document(args.timeout_ms)
        flow.dismiss_common_overlays(args.timeout_ms, source_action="post_navigate")
        if args.wait_ms > 0:
            flow.wait(args.wait_ms)

        if steps:
            for step in steps:
                flow.execute_step(step)
        else:
            flow.snapshot_dom(args.dom_file)
            flow.snapshot_png(args.screenshot)

        default_dom = output_dir / args.dom_file
        default_png = output_dir / args.screenshot
        if steps:
            if not default_dom.exists():
                flow.snapshot_dom(args.dom_file)
            if not default_png.exists():
                flow.snapshot_png(args.screenshot)

        summary.update(
            {
                "status": "ok",
                "title": flow.call_with_alert_recovery(client.title, source_action="title"),
                "final_url": flow.call_with_alert_recovery(client.current_url, source_action="current_url"),
                "steps_run": flow.steps_run,
                "observed_alerts": flow.observed_alerts,
                "dom_file": args.dom_file,
                "screenshot": args.screenshot,
                "dom_summary": summarize_dom_file(default_dom),
                "has_screenshot": default_png.exists(),
            }
        )
        write_json(output_dir / args.summary_json, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        default_dom = output_dir / args.dom_file
        default_png = output_dir / args.screenshot
        summary.update(
            {
                "status": "error",
                "error": str(exc),
                "steps_run": flow.steps_run,
                "observed_alerts": flow.observed_alerts,
                "dom_file": args.dom_file if default_dom.exists() else None,
                "screenshot": args.screenshot if default_png.exists() else None,
                "dom_summary": summarize_dom_file(default_dom),
                "has_screenshot": default_png.exists(),
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
