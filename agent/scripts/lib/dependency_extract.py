#!/usr/bin/env python3
"""Generic dependency-manifest parser.

Source-analyzer historically reads HTML/JS content but never parses
package manifest files. That leaves the supply-chain / vulnerable-
library / typosquatting bug class untested across every target.

This script is a target-agnostic parser: feed it a filename + content
(or a path) and it emits one JSON object per declared dependency,
keyed by ecosystem. Downstream checkers (dependency_check.py) then
look the dependencies up against typosquatting heuristics and / or
public CVE feeds (OSV.dev).

Generality contract:
  * Manifest filename → parser dispatch uses canonical names defined
    by the upstream package manager (package.json, requirements.txt,
    go.mod, etc.). Not target-specific.
  * No package-name embedded in the parser. The parser's only job is
    to extract whatever names + versions the manifest declares.
  * No assumption about specific frameworks. A blank or unparseable
    manifest just yields zero output, not an error.

Supported ecosystems (MVP set covering most webapp targets):
  npm       — package.json, package-lock.json (v1, v2, v3)
  pypi      — requirements.txt, Pipfile.lock
  go        — go.mod
  packagist — composer.json
  rubygems  — Gemfile.lock (best-effort, common shape)
  generic   — CDN URLs in HTML/JS body (jquery-3.5.0.min.js style)

Output:
  One JSON object per line. Schema:
    {
      "ecosystem": "<npm|pypi|go|packagist|rubygems|generic>",
      "name":      "<package-name>",
      "version":   "<version-spec>",
      "source":    "<manifest-filename or hint>",
      "dev":       <bool, optional>     # true for devDependencies
    }

Usage:
  # From stdin with explicit filename hint
  cat package.json | dependency_extract.py --filename package.json

  # From a file path (filename detected automatically)
  dependency_extract.py /path/to/package-lock.json

  # Generic CDN URL extraction from an arbitrary HTML/JS snippet
  cat page.html | dependency_extract.py --filename page.html --cdn
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# npm — package.json and package-lock.json
# ---------------------------------------------------------------------------

# npm range specifiers are messy: `^1.2.3`, `~1.2.0`, `>=1.2.0 || ^2.0.0`,
# `1.x`, etc. Post-L1 fix: extract the leading concrete SemVer with a
# regex rather than the buggy `lstrip("^~>=<=")` which (a) treated `=`
# twice (charset, not prefix), (b) left whitespace, and (c) preserved
# everything after the first range alternative. OSV.dev wants a clean
# version string; garbage in the version field silently zeros out the
# CVE lookup.
_NPM_VERSION_LEAD = re.compile(r"\s*[\^~<>=v]*\s*([0-9][^\s|,]*)")


def _sanitize_npm_version(raw: str) -> str:
    if not raw:
        return ""
    m = _NPM_VERSION_LEAD.match(str(raw))
    return m.group(1) if m else ""


def _emit_npm_dep(name: str, version: str, source: str, dev: bool = False):
    return {
        "ecosystem": "npm",
        "name": name,
        "version": _sanitize_npm_version(version),
        "source": source,
        "dev": dev,
    }


def parse_package_json(content: str, source: str = "package.json") -> list[dict]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    out = []
    for key, dev in (("dependencies", False), ("devDependencies", True),
                     ("peerDependencies", False), ("optionalDependencies", False)):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            if isinstance(name, str) and isinstance(version, str):
                out.append(_emit_npm_dep(name, version, source, dev))
    return out


def parse_package_lock(content: str, source: str = "package-lock.json") -> list[dict]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    out = []
    # lockfile v1: payload["dependencies"] = {name: {version, dev?, ...}}
    legacy = payload.get("dependencies")
    if isinstance(legacy, dict):
        for name, info in legacy.items():
            if not isinstance(name, str) or not isinstance(info, dict):
                continue
            version = info.get("version", "")
            dev = bool(info.get("dev"))
            if isinstance(version, str):
                out.append(_emit_npm_dep(name, version, source, dev))
    # lockfile v2/v3: payload["packages"] = {"node_modules/<name>": {version, dev?}}
    packages = payload.get("packages")
    if isinstance(packages, dict):
        for path, info in packages.items():
            if not isinstance(path, str) or not isinstance(info, dict):
                continue
            # Skip the root entry (path == "")
            if not path:
                continue
            # Path is "node_modules/<name>" or "node_modules/<a>/node_modules/<b>"
            tail = path.rsplit("node_modules/", 1)[-1]
            if not tail or "/" in tail and not tail.startswith("@"):
                # nested non-scoped path; take the last segment
                tail = tail.rsplit("/", 1)[-1]
            name = tail
            version = info.get("version", "")
            dev = bool(info.get("dev"))
            if isinstance(version, str):
                out.append(_emit_npm_dep(name, version, source, dev))
    return out


# ---------------------------------------------------------------------------
# pypi — requirements.txt, Pipfile.lock
# ---------------------------------------------------------------------------

# PEP 508-ish line: name [extras] op version  (op in == >= <= ~= != >)
_PIP_LINE = re.compile(
    r"^\s*"
    r"(?P<name>[A-Za-z0-9_][A-Za-z0-9_\-.]*)"   # package name
    r"(?:\s*\[[^\]]*\])?"                        # optional extras
    r"\s*"
    r"(?:(?P<op>==|>=|<=|~=|!=|>|<)"             # version operator
    r"\s*(?P<version>[A-Za-z0-9_.\-+!]+))?"      # version
    r"\s*(?:;.*)?\s*$"                           # optional env marker
)


def parse_requirements_txt(content: str, source: str = "requirements.txt") -> list[dict]:
    out = []
    for raw in content.splitlines():
        # Strip inline `#` comments before pattern-matching so trailing
        # comments don't break the line. `;` markers are PEP 508 env
        # markers (kept in the regex's tail alternation).
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-r ", "-e ", "--", "git+", "https://", "http://", "file:")):
            continue
        m = _PIP_LINE.match(line)
        if not m:
            continue
        out.append({
            "ecosystem": "pypi",
            "name": m.group("name"),
            "version": m.group("version") or "",
            "source": source,
        })
    return out


def parse_pipfile_lock(content: str, source: str = "Pipfile.lock") -> list[dict]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    out = []
    for section_key, dev in (("default", False), ("develop", True)):
        block = payload.get(section_key)
        if not isinstance(block, dict):
            continue
        for name, info in block.items():
            if not isinstance(name, str) or not isinstance(info, dict):
                continue
            version = info.get("version", "")
            if isinstance(version, str):
                # Pipfile.lock versions look like "==2.31.0"; strip the op.
                stripped = version.lstrip("=<>~!")
                out.append({
                    "ecosystem": "pypi",
                    "name": name,
                    "version": stripped,
                    "source": source,
                    "dev": dev,
                })
    return out


# ---------------------------------------------------------------------------
# go — go.mod
# ---------------------------------------------------------------------------

_GO_REQUIRE_LINE = re.compile(r"^\s*(?P<name>[a-zA-Z0-9_./\-]+)\s+(?P<version>v[0-9][^\s]*)")
_GO_REQUIRE_BLOCK_OPEN = re.compile(r"^\s*require\s*\(")
_GO_REQUIRE_BLOCK_CLOSE = re.compile(r"^\s*\)")


def parse_go_mod(content: str, source: str = "go.mod") -> list[dict]:
    out = []
    in_block = False
    for raw in content.splitlines():
        line = raw.split("//", 1)[0].rstrip()
        if not line.strip():
            continue
        if not in_block and _GO_REQUIRE_BLOCK_OPEN.match(line):
            in_block = True
            continue
        if in_block and _GO_REQUIRE_BLOCK_CLOSE.match(line):
            in_block = False
            continue
        if in_block:
            m = _GO_REQUIRE_LINE.match(line)
            if m:
                out.append({
                    "ecosystem": "go",
                    "name": m.group("name"),
                    "version": m.group("version"),
                    "source": source,
                })
        else:
            # Single-line `require name version` outside a block
            if line.lstrip().startswith("require "):
                rest = line.split("require", 1)[1].strip()
                m = _GO_REQUIRE_LINE.match(rest)
                if m:
                    out.append({
                        "ecosystem": "go",
                        "name": m.group("name"),
                        "version": m.group("version"),
                        "source": source,
                    })
    return out


# ---------------------------------------------------------------------------
# packagist — composer.json
# ---------------------------------------------------------------------------

def parse_composer_json(content: str, source: str = "composer.json") -> list[dict]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    out = []
    for key, dev in (("require", False), ("require-dev", True)):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            # composer pseudo-packages (php / ext-*) are not real deps for CVE.
            if name.startswith(("php", "ext-", "lib-", "composer-")):
                continue
            out.append({
                "ecosystem": "packagist",
                "name": name,
                "version": str(version).lstrip("^~>=< "),
                "source": source,
                "dev": dev,
            })
    return out


# ---------------------------------------------------------------------------
# rubygems — Gemfile.lock (best-effort common shape)
# ---------------------------------------------------------------------------

_GEMFILE_GEM_HEADER = re.compile(r"^GEM\s*$")
_GEMFILE_SPECS_HEADER = re.compile(r"^\s+specs:\s*$")
_GEMFILE_GEM_LINE = re.compile(r"^\s{4}(?P<name>[a-zA-Z0-9_\-]+)\s+\((?P<version>[^)]+)\)\s*$")


def parse_gemfile_lock(content: str, source: str = "Gemfile.lock") -> list[dict]:
    out = []
    in_specs = False
    for raw in content.splitlines():
        if _GEMFILE_GEM_HEADER.match(raw):
            continue
        if _GEMFILE_SPECS_HEADER.match(raw):
            in_specs = True
            continue
        if in_specs:
            m = _GEMFILE_GEM_LINE.match(raw)
            if m:
                out.append({
                    "ecosystem": "rubygems",
                    "name": m.group("name"),
                    "version": m.group("version"),
                    "source": source,
                })
            elif raw.strip() == "":
                # Blank line ends the specs block.
                in_specs = False
    return out


# ---------------------------------------------------------------------------
# generic — CDN URL version extraction from arbitrary HTML/JS content
# ---------------------------------------------------------------------------

# Captures: <prefix>/<name>-<version>(.min)?.<ext>
# Generic enough to work on jsDelivr, cdnjs, unpkg, jspm, and ad-hoc CDN hosts.
_CDN_URL = re.compile(
    r"(?:(?:https?:)?//[^\"'\s<>]+/"               # CDN scheme + host
    r"|[\"'/])"                                     # or root-relative
    r"(?P<name>[a-zA-Z0-9_\-]+)"                    # package name
    r"[-/]"                                         # name-version or name/version
    r"(?P<version>"
    r"v?[0-9]+\.[0-9]+(?:\.[0-9]+)?"                # semver
    r"(?:-[a-zA-Z0-9.\-]+)?"                        # prerelease
    r")"
    r"(?:[/\-][a-zA-Z0-9._\-]*)?"                   # path tail / minified suffix
    r"\.(?:js|css|min\.js|min\.css)"                # extension
)


def parse_cdn_versions(content: str, source: str = "html") -> list[dict]:
    out = []
    seen = set()
    for m in _CDN_URL.finditer(content):
        name = m.group("name")
        version = m.group("version").lstrip("v")
        if (name, version) in seen:
            continue
        seen.add((name, version))
        out.append({
            "ecosystem": "generic",
            "name": name,
            "version": version,
            "source": source,
        })
    return out


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH: list[tuple[str, callable]] = [
    ("package-lock.json", parse_package_lock),
    ("package.json", parse_package_json),
    ("Pipfile.lock", parse_pipfile_lock),
    ("requirements.txt", parse_requirements_txt),
    ("requirements-dev.txt", parse_requirements_txt),
    ("requirements-test.txt", parse_requirements_txt),
    ("go.mod", parse_go_mod),
    ("composer.json", parse_composer_json),
    ("Gemfile.lock", parse_gemfile_lock),
]


def dispatch_by_filename(filename: str, content: str) -> list[dict]:
    """Pick a parser based on the filename's basename. Empty list if no
    parser matches — caller can fall through to CDN extraction."""
    if not filename:
        return []
    base = filename.rsplit("/", 1)[-1].lower()
    for suffix, parser in _DISPATCH:
        if base.endswith(suffix.lower()):
            return parser(content, source=filename)
    return []


def main(argv: list[str]) -> int:
    args = argv[1:]
    filename = ""
    cdn_mode = False
    path: Path | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--filename" and i + 1 < len(args):
            filename = args[i + 1]
            i += 2
            continue
        if a == "--cdn":
            cdn_mode = True
            i += 1
            continue
        if a.startswith("-"):
            print(f"dependency_extract: unknown option {a}", file=sys.stderr)
            return 2
        path = Path(a)
        i += 1

    if path is not None:
        if not path.is_file():
            print(f"dependency_extract: not a file: {path}", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        if not filename:
            filename = path.name
    else:
        content = sys.stdin.read()

    rows: list[dict] = dispatch_by_filename(filename, content)
    if cdn_mode or (not rows and filename.endswith((".html", ".htm", ".js"))):
        rows.extend(parse_cdn_versions(content, source=filename or "stdin"))

    for row in rows:
        sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
