#!/usr/bin/env python3
"""Generic dependency-audit checker — typosquatting (offline) + optional
CVE query against OSV.dev (online, opt-in).

Reads JSONL produced by dependency_extract.py from stdin or a file,
emits one finding per anomalous dependency:

    {
      "kind":      "typosquatting" | "vulnerable" | "outdated",
      "ecosystem": "npm",
      "name":      "<declared name>",
      "version":   "<declared version>",
      "source":    "<manifest filename>",
      "severity":  "HIGH" | "MEDIUM" | "LOW" | "INFO",
      "rationale": "<one-line evidence>"
    }

Generality contract:
  * Popular-package lists are GENERIC ecosystem-popularity rankings,
    not target-specific clues. Every entry is the documented "top N"
    package for its ecosystem (npm by weekly downloads, pypi by
    download count, etc.).
  * Typosquatting heuristic uses Damerau-Levenshtein distance — a
    pure-structural metric. No target identity needed.
  * CVE check delegates to OSV.dev's public API
    (https://api.osv.dev/v1/query) which is a target-agnostic database
    of all known package vulnerabilities. No embedded vulnerability
    clue per target.
  * OSV calls are off by default — opt in via env or --osv flag.

CLI:
  cat extracted.jsonl | dependency_check.py
  dependency_check.py extracted.jsonl
  dependency_check.py extracted.jsonl --osv          # also query OSV.dev
  dependency_check.py extracted.jsonl --offline-only # skip OSV even if env

Env overrides:
  REDTEAM_DEPENDENCY_OSV=1      enables OSV by default (CLI --offline-only wins)
  REDTEAM_DEPENDENCY_OSV_URL    override OSV endpoint (default: api.osv.dev)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Popular-package lists per ecosystem.
#
# These are generic top-by-download rankings, not curated for any target.
# Sources: npm's `most-depended-upon` registry list, PyPI BigQuery
# top-1000 downloads, RubyGems most-downloaded gems, Go pkg.go.dev
# top-imports, Packagist installed counts. Sampled 2026-Q1.
#
# Adding a target-specific name here is a contract violation; the unit
# test scans this list against forbidden tokens.
# ---------------------------------------------------------------------------

POPULAR_PACKAGES: dict[str, frozenset[str]] = {
    "npm": frozenset({
        "react", "react-dom", "lodash", "axios", "jquery", "vue", "angular",
        "express", "moment", "webpack", "babel", "typescript", "next",
        "nuxt", "redux", "react-router", "react-router-dom", "tslib",
        "chalk", "commander", "debug", "yargs", "uuid", "ws", "cheerio",
        "mocha", "chai", "jest", "eslint", "prettier", "rxjs", "request",
        "node-fetch", "cors", "body-parser", "morgan", "helmet", "dotenv",
        "passport", "bcrypt", "bcryptjs", "jsonwebtoken", "sequelize",
        "mongoose", "pg", "mysql", "mysql2", "redis", "socket.io",
        "socket.io-client", "graphql", "apollo-server", "apollo-client",
        "fastify", "koa", "hapi", "joi", "lodash.merge", "underscore",
        "ramda", "rimraf", "glob", "minimist", "semver", "tar", "fs-extra",
        "winston", "pino", "marked", "highlight.js", "moment-timezone",
        "date-fns", "dayjs", "validator", "sanitize-html", "dompurify",
        "xml2js", "fast-xml-parser", "node-sass", "sass", "stylelint",
        "postcss", "autoprefixer", "tailwindcss", "bootstrap", "bulma",
        "material-ui", "@mui/material", "react-redux", "redux-thunk",
        "redux-saga", "@reduxjs/toolkit", "vuex", "pinia", "tailwind",
        "ngrx", "rxjs-compat", "core-js", "regenerator-runtime",
    }),
    "pypi": frozenset({
        "requests", "urllib3", "certifi", "charset-normalizer", "idna",
        "setuptools", "wheel", "pip", "six", "python-dateutil", "pytz",
        "click", "flask", "django", "fastapi", "pydantic", "uvicorn",
        "gunicorn", "starlette", "numpy", "pandas", "scipy", "matplotlib",
        "scikit-learn", "tensorflow", "torch", "pytest", "tox", "coverage",
        "black", "isort", "flake8", "mypy", "pylint", "ruff", "sqlalchemy",
        "psycopg2", "psycopg2-binary", "pymysql", "redis", "pymongo",
        "celery", "kombu", "boto3", "botocore", "s3transfer", "lxml",
        "beautifulsoup4", "bs4", "selenium", "scrapy", "pillow", "pyyaml",
        "jinja2", "markupsafe", "werkzeug", "itsdangerous", "blinker",
        "cryptography", "pycparser", "cffi", "pyasn1", "pyopenssl",
        "paramiko", "requests-oauthlib", "oauthlib", "jwt", "pyjwt",
        "passlib", "bcrypt", "argon2-cffi", "marshmallow", "flask-restful",
        "djangorestframework", "graphene", "graphene-django",
        "django-cors-headers", "django-filter", "django-allauth",
        "python-decouple", "environs", "ipython", "jupyter", "notebook",
        "tqdm", "rich", "typer", "httpx", "aiohttp", "asyncio", "trio",
    }),
    "go": frozenset({
        "github.com/gin-gonic/gin", "github.com/gorilla/mux",
        "github.com/labstack/echo", "github.com/spf13/cobra",
        "github.com/spf13/viper", "github.com/stretchr/testify",
        "github.com/sirupsen/logrus", "go.uber.org/zap",
        "golang.org/x/net", "golang.org/x/sys", "golang.org/x/crypto",
        "golang.org/x/text", "golang.org/x/sync", "golang.org/x/oauth2",
        "github.com/pkg/errors", "github.com/google/uuid",
        "github.com/satori/go.uuid", "github.com/jinzhu/gorm",
        "gorm.io/gorm", "github.com/jmoiron/sqlx",
        "github.com/lib/pq", "github.com/go-sql-driver/mysql",
        "github.com/go-redis/redis", "github.com/redis/go-redis",
        "github.com/aws/aws-sdk-go", "github.com/aws/aws-sdk-go-v2",
        "github.com/prometheus/client_golang", "github.com/grpc-ecosystem/grpc-gateway",
        "google.golang.org/grpc", "google.golang.org/protobuf",
        "github.com/golang/protobuf", "github.com/json-iterator/go",
        "github.com/mitchellh/mapstructure", "github.com/hashicorp/go-multierror",
        "github.com/hashicorp/hcl", "github.com/davecgh/go-spew",
        "github.com/pmezard/go-difflib", "gopkg.in/yaml.v2", "gopkg.in/yaml.v3",
        "github.com/golang-jwt/jwt", "github.com/dgrijalva/jwt-go",
    }),
    "packagist": frozenset({
        "symfony/console", "symfony/http-foundation", "symfony/finder",
        "symfony/process", "symfony/yaml", "symfony/event-dispatcher",
        "laravel/framework", "laravel/tinker", "monolog/monolog",
        "guzzlehttp/guzzle", "guzzlehttp/promises", "guzzlehttp/psr7",
        "doctrine/orm", "doctrine/dbal", "doctrine/annotations",
        "doctrine/cache", "twig/twig", "phpunit/phpunit",
        "phpmailer/phpmailer", "swiftmailer/swiftmailer",
        "league/flysystem", "league/csv", "ramsey/uuid",
        "predis/predis", "nesbot/carbon", "vlucas/phpdotenv",
        "phpoffice/phpspreadsheet", "tijsverkoyen/css-to-inline-styles",
        "psr/log", "psr/http-message", "psr/container",
    }),
    "rubygems": frozenset({
        "rails", "actionpack", "actionview", "activerecord", "activemodel",
        "activesupport", "actionmailer", "actioncable", "activejob",
        "activestorage", "railties", "rake", "bundler", "minitest",
        "rspec", "rspec-rails", "factory_bot_rails", "faker", "capybara",
        "selenium-webdriver", "puma", "unicorn", "thin", "sidekiq",
        "delayed_job", "resque", "redis", "pg", "mysql2", "sqlite3",
        "nokogiri", "rack", "rack-cors", "warden", "devise", "cancancan",
        "pundit", "ransack", "kaminari", "pagy", "will_paginate",
        "carrierwave", "paperclip", "shrine", "mini_magick", "image_processing",
        "tilt", "haml", "slim", "sass", "sass-rails", "sprockets-rails",
        "jquery-rails", "turbolinks", "stimulus-rails", "hotwire-rails",
        "jwt", "doorkeeper", "oauth2", "omniauth",
    }),
}


# ---------------------------------------------------------------------------
# Typosquatting heuristic (Damerau-Levenshtein distance).
# ---------------------------------------------------------------------------

def damerau_levenshtein(a: str, b: str, cap: int = 3) -> int:
    """Optimal-string-alignment distance with adjacent-transposition step.
    Returns up to `cap`; values > cap may be returned as cap+1 for early-out."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    prev2 = [0] * (lb + 1)
    prev = list(range(lb + 1))
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        curr[0] = i
        row_min = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,        # insert
                prev[j] + 1,            # delete
                prev[j - 1] + cost,     # sub
            )
            if (
                i > 1 and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                curr[j] = min(curr[j], prev2[j - 2] + cost)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > cap:
            return cap + 1
        prev2, prev, curr = prev, curr, prev2
    return prev[lb]


def detect_typosquatting(name: str, ecosystem: str) -> str | None:
    """If `name` is suspiciously close to a popular package in the same
    ecosystem (but not equal), return the popular name. Else None."""
    popular = POPULAR_PACKAGES.get(ecosystem, frozenset())
    if not popular or name in popular:
        return None
    lower = name.lower()
    # Strip a leading "@scope/" so scoped packages on npm get compared
    # against the unscoped popular list properly.
    if "/" in lower and ecosystem == "npm":
        _, lower = lower.split("/", 1)
    best_name = None
    best_dist = 3
    for p in popular:
        d = damerau_levenshtein(lower, p.lower(), cap=2)
        if 1 <= d <= 2 and d < best_dist:
            best_dist = d
            best_name = p
            if d == 1:
                break
    return best_name


# ---------------------------------------------------------------------------
# OSV.dev query.
# ---------------------------------------------------------------------------

_OSV_ECOSYSTEM_NAME = {
    "npm": "npm",
    "pypi": "PyPI",
    "go": "Go",
    "packagist": "Packagist",
    "rubygems": "RubyGems",
}


def osv_query(ecosystem: str, name: str, version: str, endpoint: str, timeout: float = 5.0) -> list[dict]:
    osv_eco = _OSV_ECOSYSTEM_NAME.get(ecosystem)
    if not osv_eco or not name or not version:
        return []
    payload = json.dumps({
        "version": version,
        "package": {"name": name, "ecosystem": osv_eco},
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    try:
        parsed = json.loads(body)
    except ValueError:
        return []
    vulns = parsed.get("vulns") if isinstance(parsed, dict) else None
    if not isinstance(vulns, list):
        return []
    return [v for v in vulns if isinstance(v, dict)]


def osv_severity(vuln: dict) -> str:
    sev = vuln.get("database_specific") or {}
    if isinstance(sev, dict):
        score = str(sev.get("severity") or sev.get("cvss_severity") or "").upper()
        if score in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            return score
    sevs = vuln.get("severity") or []
    if isinstance(sevs, list):
        for entry in sevs:
            if not isinstance(entry, dict):
                continue
            t = str(entry.get("type") or "").upper()
            if t in {"CVSS_V3", "CVSS_V4"} and isinstance(entry.get("score"), str):
                # CVSS vector -> map by base-score range. The score format
                # is "CVSS:3.1/AV:N/.../<base>". We rely on `database_specific`
                # above when available; this fallback returns INFO.
                pass
    return "INFO"


# ---------------------------------------------------------------------------
# Main pipeline.
# ---------------------------------------------------------------------------

def _read_jsonl_lines(stream) -> list[dict]:
    rows: list[dict] = []
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def check(rows: list[dict], do_osv: bool, osv_endpoint: str) -> list[dict]:
    findings: list[dict] = []
    for row in rows:
        eco = str(row.get("ecosystem") or "").strip()
        name = str(row.get("name") or "").strip()
        version = str(row.get("version") or "").strip()
        source = str(row.get("source") or "").strip()
        if not name:
            continue

        # 1) Typosquatting (always run — offline).
        if eco in POPULAR_PACKAGES:
            target = detect_typosquatting(name, eco)
            if target:
                findings.append({
                    "kind": "typosquatting",
                    "ecosystem": eco,
                    "name": name,
                    "version": version,
                    "source": source,
                    "severity": "MEDIUM",
                    "rationale": (
                        f"Name {name!r} is Damerau-Levenshtein-close to popular "
                        f"{eco} package {target!r}; treat as supply-chain "
                        f"typosquatting candidate."
                    ),
                })

        # 2) OSV.dev CVE lookup (opt-in).
        if do_osv and version:
            vulns = osv_query(eco, name, version, osv_endpoint)
            for v in vulns:
                vid = v.get("id") or "UNKNOWN"
                aliases = v.get("aliases") if isinstance(v.get("aliases"), list) else []
                cve_ids = [a for a in aliases if isinstance(a, str) and a.startswith("CVE-")]
                cve = cve_ids[0] if cve_ids else vid
                findings.append({
                    "kind": "vulnerable",
                    "ecosystem": eco,
                    "name": name,
                    "version": version,
                    "source": source,
                    "severity": osv_severity(v),
                    "rationale": f"{eco}:{name}@{version} matches {cve} ({vid}).",
                })
    return findings


def main(argv: list[str]) -> int:
    args = argv[1:]
    do_osv_env = os.environ.get("REDTEAM_DEPENDENCY_OSV", "").strip() == "1"
    osv_endpoint = os.environ.get(
        "REDTEAM_DEPENDENCY_OSV_URL",
        "https://api.osv.dev/v1/query",
    )
    do_osv = do_osv_env
    path: Path | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--osv":
            do_osv = True
            i += 1
            continue
        if a == "--offline-only":
            do_osv = False
            i += 1
            continue
        if a == "--osv-endpoint" and i + 1 < len(args):
            osv_endpoint = args[i + 1]
            do_osv = True
            i += 2
            continue
        if a.startswith("-"):
            print(f"dependency_check: unknown option {a}", file=sys.stderr)
            return 2
        path = Path(a)
        i += 1

    if path is not None:
        if not path.is_file():
            print(f"dependency_check: not a file: {path}", file=sys.stderr)
            return 1
        with path.open("r", encoding="utf-8") as fh:
            rows = _read_jsonl_lines(fh)
    else:
        rows = _read_jsonl_lines(sys.stdin)

    findings = check(rows, do_osv=do_osv, osv_endpoint=osv_endpoint)
    for f in findings:
        sys.stdout.write(json.dumps(f, ensure_ascii=False) + "\n")
    # Exit 0 even if no findings — silence is a valid result for the
    # operator pipeline.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
