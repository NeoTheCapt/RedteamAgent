#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

FINDING_SECTION_PATTERN = re.compile(
    r"^## \[(?P<id>[^\]]+)\] (?P<title>.+?)\n(?P<body>.*?)(?=^## \[|\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
FINDING_FIELD_PATTERN = re.compile(r"^- \*\*(?P<key>[^*]+)\*\*: (?P<value>.*)$", flags=re.MULTILINE)
SECURITY_SHORT_TOKENS = {
    "xss", "xxe", "idor", "bola", "ssrf", "sqli", "sql", "jwt", "csrf", "rce", "ssti",
    "dos", "2fa", "api", "xml", "oauth", "csp", "osint", "idor", "lfi", "xxe", "ws",
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "via", "page", "pages",
    "field", "fields", "bonus", "payload", "challenge", "challenges", "legacy", "issue", "issues",
    "missing", "attack", "vector", "various", "endpoint", "endpoints", "true", "false", "query",
    "parameter", "parameters", "based", "stored", "reflected", "client", "server", "side", "flow",
    "data", "exposure", "disclosure", "bypass", "protection", "exploit", "continued", "continue",
    "attackers", "attacker", "response", "responses", "result", "results", "login", "user", "users",
    "product", "products", "review", "reviews", "rest", "api", "http", "https", "path", "upload",
    "various", "entry", "point", "points", "root", "support", "team", "admin", "password",
}
VULN_FAMILY_HINTS = {
    "sql", "injection", "nosql", "xss", "xxe", "jwt", "redirect", "idor", "bola", "ssrf",
    "captcha", "metrics", "deserialization", "header", "headers", "csrf", "oauth", "file",
    "traversal", "listing", "null", "byte", "race", "condition", "brute", "force", "upload",
    "template", "supply", "chain", "misconfiguration", "crypto", "cryptographic", "authorization",
    "authentication", "access", "control", "business", "logic", "open", "directory", "steganography",
    "policy", "security", "sensitive", "coupon", "graphql", "xml", "redirects", "component",
    "documentation", "swagger", "openapi", "schema", "credentials", "credential", "hardcoded",
    "password", "backup", "exif", "enumeration", "redirect", "redirects", "login", "throttling",
    "lockout", "rate", "limit", "debug", "stack", "trace", "configuration", "unauthenticated",
    "privilege", "logs", "logging", "secret", "leak",
}
GENERIC_FAMILY_TOKENS = {
    "access", "control", "security", "authentication", "authorization", "business", "logic",
    "policy", "sensitive", "data", "information", "exposure", "disclosure", "input", "validation",
    "component", "components", "issue", "issues", "directory", "open", "file", "misconfiguration",
}
CATEGORY_ALIAS_TOKENS = {
    'broken access control': {'access', 'control', 'idor', 'bola', 'authorization', 'unauthenticated', 'forced', 'browsing', 'privilege'},
    'broken authentication': {'authentication', 'credential', 'credentials', 'password', 'oauth', '2fa', 'login', 'session', 'account'},
    'broken anti automation': {'automation', 'captcha', 'brute', 'throttling', 'lockout', 'rate', 'limit', 'enumeration', 'race'},
    'security misconfiguration': {'misconfiguration', 'swagger', 'openapi', 'metrics', 'headers', 'debug', 'stack', 'trace', 'configuration'},
    'sensitive data exposure': {'sensitive', 'exposure', 'leak', 'backup', 'claims', 'secret', 'token', 'jwt', 'exif'},
    'observability failures': {'logs', 'logging', 'metrics', 'trace', 'stack', 'access', 'audit'},
    'unvalidated redirects': {'redirect', 'allowlist', 'whitelist', 'target'},
    'injection': {'injection', 'sql', 'nosql', 'ssti', 'template'},
    'xss': {'xss', 'dom', 'csp', 'reflected', 'stored', 'subtitle'},
    'xxe': {'xxe', 'xml', 'entity'},
    'insecure deserialization': {'deserialization', 'rce', 'object'},
    'improper input validation': {'validation', 'upload', 'mass', 'assignment', 'quantity', 'coupon'},
    'vulnerable components': {'supply', 'dependency', 'component', 'jwt', 'typosquatting', 'unsigned'},
    'cryptographic issues': {'crypto', 'cryptographic', 'hash', 'coupon', 'key'},
}


@dataclass
class BenchmarkItem:
    category: str
    challenge: str
    cwe: str
    attack_vector: str
    endpoint: str
    automation: str
    endpoint_candidates: list[str]
    text_tokens: set[str]


@dataclass
class BenchmarkGroup:
    key: str
    category: str
    automation: str
    endpoint_candidates: list[str]
    text_tokens: set[str]
    member_indexes: list[int]
    label: str


@dataclass
class Finding:
    finding_id: str
    title: str
    severity: str
    finding_type: str
    owasp_category: str
    parameter: str
    evidence: str
    text_tokens: set[str]
    endpoint_candidates: list[str]


@dataclass
class Match:
    score: int
    finding_index: int
    benchmark_index: int
    shared_tokens: list[str]
    endpoint_match: str
    reason: str = ""


def load_snapshot() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("expected run snapshot JSON on stdin")
    return json.loads(raw)


def parse_findings_markdown(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in FINDING_SECTION_PATTERN.finditer(text):
        payload: dict[str, str] = {
            "original_id": match.group("id").strip(),
            "title": match.group("title").strip(),
            "body": match.group("body").strip(),
        }
        for field in FINDING_FIELD_PATTERN.finditer(payload["body"]):
            key = field.group("key").strip().lower().replace(" ", "_")
            payload[key] = field.group("value").strip()
        corpus = " ".join(
            [
                payload.get("title", ""),
                payload.get("type", ""),
                payload.get("owasp_category", ""),
                payload.get("parameter", ""),
                payload.get("evidence", ""),
            ]
        )
        findings.append(
            Finding(
                finding_id=payload.get("original_id", ""),
                title=payload.get("title", ""),
                severity=str(payload.get("severity", "INFO")).upper(),
                finding_type=payload.get("type", ""),
                owasp_category=payload.get("owasp_category", ""),
                parameter=payload.get("parameter", ""),
                evidence=payload.get("evidence", ""),
                text_tokens=(tokenize(corpus) | category_alias_tokens(payload.get("owasp_category", "") + " " + payload.get("type", ""))),
                endpoint_candidates=extract_endpoint_candidates(corpus),
            )
        )
    return findings


def resolve_benchmark_path(target: str, mapping_path: Path, root_dir: Path | None) -> tuple[Path | None, str]:
    if not mapping_path.exists():
        return None, ""
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    entry = ((payload.get("targets") or {}).get(target) or {}) if isinstance(payload, dict) else {}
    benchmark = str(entry.get("benchmark") or "").strip()
    label = str(entry.get("label") or "").strip()
    if not benchmark:
        return None, label
    candidate = Path(benchmark)
    if not candidate.is_absolute():
        candidate = (mapping_path.parent / candidate).resolve()
    if root_dir is not None and not candidate.exists():
        alt = (root_dir / benchmark).resolve()
        if alt.exists():
            candidate = alt
    return candidate, label


def parse_markdown_table(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int]:
    header = [cell.strip() for cell in lines[start].strip().strip("|").split("|")]
    rows: list[list[str]] = []
    index = start + 2
    while index < len(lines):
        line = lines[index].rstrip("\n")
        if not line.strip().startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        index += 1
    return header, rows, index


def normalize_category_heading(line: str) -> str:
    heading = re.sub(r"^#+\s*", "", line).strip()
    heading = re.sub(r"^\d+(?:\.\d+)*\s+", "", heading)
    heading = re.sub(r"\s*\([^)]*\)\s*$", "", heading)
    return heading.strip()


def parse_benchmark_markdown(path: Path) -> tuple[list[BenchmarkItem], dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    category_automation: dict[str, str] = {}
    items: list[BenchmarkItem] = []
    current_category = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## ") and "漏洞分类汇总" in line:
            table_start = index + 1
            while table_start < len(lines) and not lines[table_start].strip():
                table_start += 1
            if table_start >= len(lines) or not lines[table_start].strip().startswith("|"):
                index += 1
                continue
            headers, rows, index = parse_markdown_table(lines, table_start)
            header_map = {name: pos for pos, name in enumerate(headers)}
            if "分类" in header_map and "自动化扫描可覆盖度" in header_map:
                for row in rows:
                    if len(row) <= max(header_map.values()):
                        continue
                    category = row[header_map["分类"]].strip()
                    automation = row[header_map["自动化扫描可覆盖度"]].strip()
                    if category and category != "**合计**":
                        category_automation[category] = automation
            continue
        if line.startswith("### "):
            current_category = normalize_category_heading(line)
            index += 1
            continue
        if current_category and line.strip().startswith("|") and "Challenge" in line and "Endpoint" in line:
            headers, rows, index = parse_markdown_table(lines, index)
            header_map = {name: pos for pos, name in enumerate(headers)}
            required = ["Challenge", "CWE", "攻击向量", "关键 Endpoint"]
            if not all(name in header_map for name in required):
                continue
            for row in rows:
                if len(row) <= max(header_map.values()):
                    continue
                challenge = row[header_map["Challenge"]].strip()
                cwe = row[header_map["CWE"]].strip()
                attack = row[header_map["攻击向量"]].strip()
                endpoint = row[header_map["关键 Endpoint"]].strip()
                if not challenge:
                    continue
                automation = category_automation.get(current_category, "未知")
                corpus = " ".join([current_category, challenge, cwe, attack, endpoint])
                items.append(
                    BenchmarkItem(
                        category=current_category,
                        challenge=challenge,
                        cwe=cwe,
                        attack_vector=attack,
                        endpoint=endpoint,
                        automation=automation,
                        endpoint_candidates=extract_endpoint_candidates(endpoint, allow_textual_fallback=True),
                        text_tokens=(tokenize(corpus) | category_alias_tokens(current_category)),
                    )
                )
            continue
        index += 1
    return items, category_automation


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> set[str]:
    normalized = normalize_text(text)
    tokens = re.findall(r"[a-z0-9_+#-]+", normalized)
    output: set[str] = set()
    for token in tokens:
        token = token.strip("-_")
        if not token:
            continue
        if token in SECURITY_SHORT_TOKENS:
            output.add(token)
            continue
        if token in STOPWORDS:
            continue
        if token.startswith("cwe-"):
            output.add(token)
            continue
        if token.isdigit():
            continue
        if len(token) >= 3:
            output.add(token)
    return output


def category_alias_tokens(text: str) -> set[str]:
    normalized = normalize_text(text)
    output: set[str] = set()
    for label, aliases in CATEGORY_ALIAS_TOKENS.items():
        if label in normalized:
            output.update(aliases)
    return output


def specific_family_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token in VULN_FAMILY_HINTS and token not in GENERIC_FAMILY_TOKENS}


def generic_family_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token in VULN_FAMILY_HINTS and token in GENERIC_FAMILY_TOKENS}


def build_benchmark_groups(items: list[BenchmarkItem]) -> list[BenchmarkGroup]:
    grouped: dict[str, BenchmarkGroup] = {}
    for index, item in enumerate(items):
        endpoint_key = item.endpoint_candidates[0] if item.endpoint_candidates else normalize_text(item.endpoint or item.category)
        family_tokens = sorted(specific_family_tokens(item.text_tokens))
        if not family_tokens:
            family_tokens = sorted(token for token in item.text_tokens if token not in STOPWORDS)[:3]
        key = f"{endpoint_key}||{'/'.join(family_tokens[:3])}"
        group = grouped.get(key)
        if group is None:
            group = BenchmarkGroup(
                key=key,
                category=item.category,
                automation=item.automation,
                endpoint_candidates=list(item.endpoint_candidates),
                text_tokens=set(item.text_tokens),
                member_indexes=[index],
                label=f"{item.category}: {item.challenge}",
            )
            grouped[key] = group
        else:
            group.member_indexes.append(index)
            group.text_tokens.update(item.text_tokens)
            for endpoint in item.endpoint_candidates:
                if endpoint not in group.endpoint_candidates:
                    group.endpoint_candidates.append(endpoint)
            if coverage_bucket(item.automation) in {"high", "medium"} and coverage_bucket(group.automation) not in {"high", "medium"}:
                group.automation = item.automation
    return list(grouped.values())


def normalize_endpoint(candidate: str) -> str:
    candidate = candidate.strip().strip("`'")
    candidate = re.sub(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+", "", candidate, flags=re.I)
    candidate = candidate.replace("host.docker.internal", "127.0.0.1")
    candidate = candidate.replace("{id}", "{param}")
    candidate = re.sub(r"<[^>]+>", "{param}", candidate)
    candidate = normalize_text(candidate)
    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlparse(candidate)
        path = parsed.path or "/"
        if parsed.query:
            query_keys = sorted({chunk.split("=", 1)[0] for chunk in parsed.query.split("&") if chunk})
            return path + ("?" + "&".join(query_keys) if query_keys else "")
        return path
    if candidate.startswith("/") or candidate.startswith("#/"):
        candidate = candidate.replace("#", "")
        if "?" in candidate:
            base, query = candidate.split("?", 1)
            query_keys = sorted({chunk.split("=", 1)[0] for chunk in query.split("&") if chunk})
            return base + ("?" + "&".join(query_keys) if query_keys else "")
        return candidate
    return candidate


def extract_endpoint_candidates(text: str, allow_textual_fallback: bool = False) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"`([^`]+)`", text):
        normalized = normalize_endpoint(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    for raw in re.findall(r"https?://[^\s)>'\"]+", text):
        normalized = normalize_endpoint(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    for raw in re.findall(r"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_./?={}%:-]+)", text, flags=re.I):
        normalized = normalize_endpoint(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    for raw in re.findall(r"(/[A-Za-z0-9_./?={}%:-]{3,})", text):
        normalized = normalize_endpoint(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    if allow_textual_fallback and not candidates:
        normalized = normalize_endpoint(text)
        if normalized and len(normalized) <= 80 and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def endpoint_score(finding_eps: Iterable[str], benchmark_eps: Iterable[str]) -> tuple[int, str]:
    best_score = 0
    best_label = "none"
    for found in finding_eps:
        found_norm = normalize_endpoint(found)
        found_segments = {segment for segment in re.split(r"[/?&=\s]+", found_norm) if segment and segment not in {"{param}"}}
        for expected in benchmark_eps:
            expected_norm = normalize_endpoint(expected)
            expected_segments = {segment for segment in re.split(r"[/?&=\s]+", expected_norm) if segment and segment not in {"{param}"}}
            if found_norm == expected_norm:
                return 8, f"exact:{expected_norm}"
            if found_norm and expected_norm and (found_norm.startswith(expected_norm) or expected_norm.startswith(found_norm)):
                if best_score < 6:
                    best_score = 6
                    best_label = f"prefix:{expected_norm}"
            overlap = len(found_segments & expected_segments)
            if overlap >= 3 and best_score < 5:
                best_score = 5
                best_label = f"segments:{expected_norm}"
            elif overlap >= 2 and best_score < 4:
                best_score = 4
                best_label = f"segments:{expected_norm}"
            elif overlap >= 1 and best_score < 3 and (' ' in found_norm or ' ' in expected_norm):
                best_score = 3
                best_label = f"textual:{expected_norm}"
    return best_score, best_label


def match_score(finding: Finding, item: BenchmarkItem | BenchmarkGroup) -> tuple[int, list[str], str]:
    shared_specific = sorted(specific_family_tokens(finding.text_tokens) & specific_family_tokens(item.text_tokens))
    shared_generic = sorted(generic_family_tokens(finding.text_tokens) & generic_family_tokens(item.text_tokens))
    ep_score, ep_label = endpoint_score(finding.endpoint_candidates, item.endpoint_candidates)
    category_overlap = 1 if normalize_text(item.category) in normalize_text(finding.owasp_category + ' ' + finding.title + ' ' + finding.finding_type) else 0
    score = ep_score + (len(shared_specific) * 2) + min(len(shared_generic), 1) + category_overlap
    return score, shared_specific or shared_generic, ep_label


def choose_matches(findings: list[Finding], items: list[BenchmarkItem | BenchmarkGroup]) -> list[Match]:
    candidates: list[Match] = []
    for f_idx, finding in enumerate(findings):
        for b_idx, item in enumerate(items):
            score, shared, ep_label = match_score(finding, item)
            if ep_label == "none":
                continue
            shared_specific = specific_family_tokens(finding.text_tokens) & specific_family_tokens(item.text_tokens)
            if shared_specific and score >= 8:
                candidates.append(Match(score=score, finding_index=f_idx, benchmark_index=b_idx, shared_tokens=shared, endpoint_match=ep_label))
            elif not shared_specific and ep_label.startswith("exact:") and score >= 13:
                candidates.append(Match(score=score, finding_index=f_idx, benchmark_index=b_idx, shared_tokens=shared, endpoint_match=ep_label))
    candidates.sort(key=lambda entry: (-entry.score, entry.finding_index, entry.benchmark_index))
    used_findings: set[int] = set()
    used_items: set[int] = set()
    chosen: list[Match] = []
    for candidate in candidates:
        if candidate.finding_index in used_findings or candidate.benchmark_index in used_items:
            continue
        used_findings.add(candidate.finding_index)
        used_items.add(candidate.benchmark_index)
        chosen.append(candidate)
    return chosen


def parse_hermes_judge_output(output: str) -> dict:
    start = output.find('{')
    if start < 0:
        raise ValueError('hermes-runtime judge did not emit JSON payload')
    return json.loads(output[start:])


def judge_matches_with_llm(findings: list[Finding], items: list[BenchmarkItem], hermes_bin: str) -> list[Match]:
    benchmark_lines = []
    benchmark_ids: dict[str, int] = {}
    for index, item in enumerate(items, start=1):
        benchmark_id = f"B{index:03d}"
        benchmark_ids[benchmark_id] = index - 1
        benchmark_lines.append(
            f"{benchmark_id} | category={item.category} | challenge={item.challenge} | "
            f"attack={item.attack_vector} | endpoint={item.endpoint or '(none)'} | automation={item.automation}"
        )

    finding_lines = []
    finding_ids: dict[str, int] = {}
    for index, finding in enumerate(findings):
        finding_ids[finding.finding_id] = index
        evidence = normalize_text(finding.evidence)[:240]
        finding_lines.append(
            f"{finding.finding_id} | title={finding.title} | severity={finding.severity} | "
            f"type={finding.finding_type or '(none)'} | owasp={finding.owasp_category or '(none)'} | "
            f"parameter={finding.parameter or '(none)'} | evidence={evidence or '(none)'}"
        )

    prompt = (
        "You are a security benchmark judge. Match recorded automated findings to benchmark challenge items.\n"
        "Rules:\n"
        "- Final matching must be semantic, not regex-based.\n"
        "- A match is valid only when the finding and benchmark item describe the same vulnerability scenario or a clearly corresponding exploitation objective.\n"
        "- Do NOT match purely because the endpoint is similar. Endpoint is only supporting evidence.\n"
        "- Prefer precision over optimistic matching. If unsure, leave the finding unmatched.\n"
        "- Keep benchmark ids unique: one benchmark item can be matched at most once.\n"
        "- Do not use target-specific shortcuts or Juice-Shop-specific answer keys; judge from the finding text and benchmark item semantics only.\n"
        "- Output JSON only with this schema: {\"matches\":[{\"finding_id\":\"...\",\"benchmark_id\":\"B001\",\"confidence\":\"high|medium|low\",\"reason\":\"...\"}]}\n\n"
        "Benchmark items:\n" + "\n".join(benchmark_lines) + "\n\n"
        "Recorded findings:\n" + "\n".join(finding_lines)
    )

    result = subprocess.run(
        [hermes_bin, 'agent', '--local', '--agent', 'main', '--json', '--thinking', 'low', '--timeout', '180', '--message', prompt],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'hermes-runtime judge failed with {result.returncode}')
    payload = parse_hermes_judge_output((result.stdout or '') + (result.stderr or ''))
    raw_text = ''.join((item.get('text') or '') for item in (payload.get('payloads') or []))
    judge_output = json.loads(raw_text)

    matches: list[Match] = []
    used_findings: set[int] = set()
    used_benchmarks: set[int] = set()
    confidence_bonus = {'high': 2, 'medium': 1, 'low': 0}
    for entry in judge_output.get('matches') or []:
        finding_id = str(entry.get('finding_id') or '').strip()
        benchmark_id = str(entry.get('benchmark_id') or '').strip()
        if finding_id not in finding_ids or benchmark_id not in benchmark_ids:
            continue
        f_idx = finding_ids[finding_id]
        b_idx = benchmark_ids[benchmark_id]
        if f_idx in used_findings or b_idx in used_benchmarks:
            continue
        used_findings.add(f_idx)
        used_benchmarks.add(b_idx)
        judge_reason = str(entry.get('reason') or '').strip()
        reason_tokens = sorted(tokenize(judge_reason))[:6]
        score = 10 + confidence_bonus.get(str(entry.get('confidence') or '').lower(), 0)
        matches.append(Match(score=score, finding_index=f_idx, benchmark_index=b_idx, shared_tokens=reason_tokens, endpoint_match='llm-judge', reason=judge_reason))
    return matches


def coverage_bucket(value: str) -> str:
    normalized = value.strip().lower()
    if any(token in normalized for token in ["高", "high"]):
        return "high"
    if any(token in normalized for token in ["中", "medium"]):
        return "medium"
    if any(token in normalized for token in ["低", "low"]):
        return "low"
    return "unknown"


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def fmt_ratio(value: float) -> str:
    return f"{value:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate findings precision/recall against a markdown benchmark.")
    parser.add_argument("--mapping", required=True, help="Path to target benchmark mapping JSON.")
    parser.add_argument("--root-dir", default="", help="Optional local-hermes-agent root for resolving relative benchmark paths.")
    parser.add_argument("--label", default="", help="Human label override.")
    parser.add_argument("--hermes-bin", default="hermes", help="Hermes-runtime CLI binary used for LLM judging. Resolved via PATH; override if hermes is not in PATH.")
    args = parser.parse_args()

    snapshot = load_snapshot()
    target = str((((snapshot.get("summary") or {}).get("target") or {}).get("target")) or "").strip()
    mapping_path = Path(args.mapping)
    root_dir = Path(args.root_dir).resolve() if args.root_dir else None
    benchmark_path, benchmark_label = resolve_benchmark_path(target, mapping_path, root_dir)

    label = args.label.strip() or benchmark_label or "Benchmark evaluation"

    if not benchmark_path or not benchmark_path.exists():
        print("- No benchmark configured for this target.")
        return

    items, category_automation = parse_benchmark_markdown(benchmark_path)
    if not items:
        print(f"- Benchmark file exists but no comparable items were parsed: {benchmark_path}")
        return

    engagement_dir = Path(str((((snapshot.get("artifact") or {}).get("files") or {}).get("engagement_dir")) or "").strip())
    findings_path = engagement_dir / "findings.md"
    findings_text = findings_path.read_text(encoding="utf-8", errors="replace") if findings_path.exists() else ""
    findings = parse_findings_markdown(findings_text)
    try:
        matches = judge_matches_with_llm(findings, items, args.hermes_bin)
    except Exception as exc:
        print(f"### {label}\n")
        print(f"- benchmark_file: `{benchmark_path}`")
        print(f"- target: {target or '(unknown)' }")
        print(f"- findings_path: `{findings_path}`")
        print(f"- judge_error: {exc}")
        print("- matching_policy: LLM judge failed; no benchmark metrics emitted.")
        return
    groups = build_benchmark_groups(items)

    matched_item_indexes = {entry.benchmark_index for entry in matches}
    matched_finding_indexes = {entry.finding_index for entry in matches}
    tp = len(matches)
    fp = max(len(findings) - tp, 0)
    fn = max(len(items) - tp, 0)
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = 0.0 if precision + recall == 0 else (2 * precision * recall / (precision + recall))

    matched_group_indexes = {
        group_index
        for group_index, group in enumerate(groups)
        if any(member in matched_item_indexes for member in group.member_indexes)
    }
    scenario_tp = len(matched_group_indexes)
    scenario_fp = max(len(findings) - len(matched_finding_indexes), 0)
    scenario_fn = max(len(groups) - scenario_tp, 0)
    scenario_precision = ratio(scenario_tp, scenario_tp + scenario_fp)
    scenario_recall = ratio(scenario_tp, scenario_tp + scenario_fn)
    scenario_f1 = 0.0 if scenario_precision + scenario_recall == 0 else (2 * scenario_precision * scenario_recall / (scenario_precision + scenario_recall))

    automation_items = [index for index, item in enumerate(items) if coverage_bucket(item.automation) in {"high", "medium"}]
    automation_tp = sum(1 for index in automation_items if index in matched_item_indexes)
    automation_fn = len(automation_items) - automation_tp
    automation_recall = ratio(automation_tp, automation_tp + automation_fn)

    automation_groups = [index for index, group in enumerate(groups) if coverage_bucket(group.automation) in {"high", "medium"}]
    scenario_automation_tp = sum(1 for index in automation_groups if index in matched_group_indexes)
    scenario_automation_fn = len(automation_groups) - scenario_automation_tp
    scenario_automation_recall = ratio(scenario_automation_tp, scenario_automation_tp + scenario_automation_fn)

    by_category: dict[str, dict[str, int]] = {}
    for index, item in enumerate(items):
        bucket = by_category.setdefault(item.category, {"expected": 0, "matched": 0})
        bucket["expected"] += 1
        if index in matched_item_indexes:
            bucket["matched"] += 1

    unmatched_expected = [item for index, item in enumerate(items) if index not in matched_item_indexes]
    unmatched_findings = [finding for index, finding in enumerate(findings) if index not in matched_finding_indexes]

    print(f"### {label}\n")
    print(f"- benchmark_file: `{benchmark_path}`")
    print(f"- target: {target or '(unknown)'}")
    print(f"- findings_path: `{findings_path}`")
    print(f"- expected_items: {len(items)}")
    print(f"- actual_findings: {len(findings)}")
    print(f"- matched_true_positives: {tp}")
    print(f"- false_positives: {fp}")
    print(f"- false_negatives: {fn}")
    print(f"- precision: {fmt_ratio(precision)}")
    print(f"- recall: {fmt_ratio(recall)}")
    print(f"- f1: {fmt_ratio(f1)}")
    print(f"- automation_actionable_items (high/medium): {len(automation_items)}")
    print(f"- automation_actionable_recall: {fmt_ratio(automation_recall)}")
    print(f"- benchmark_scenarios: {len(groups)}")
    print(f"- scenario_true_positives: {scenario_tp}")
    print(f"- scenario_false_positives: {scenario_fp}")
    print(f"- scenario_false_negatives: {scenario_fn}")
    print(f"- scenario_precision: {fmt_ratio(scenario_precision)}")
    print(f"- scenario_recall: {fmt_ratio(scenario_recall)}")
    print(f"- scenario_f1: {fmt_ratio(scenario_f1)}")
    print(f"- scenario_automation_actionable_items (high/medium): {len(automation_groups)}")
    print(f"- scenario_automation_actionable_recall: {fmt_ratio(scenario_automation_recall)}")
    print("- matching_policy: LLM judge prompt decides benchmark↔finding alignment; regex/rules are used only for markdown parsing and post-match metric aggregation (target-specific hardcoding disabled)")

    print("\n#### Category coverage\n")
    for category, counts in sorted(by_category.items(), key=lambda pair: (pair[0].lower(), pair[0])):
        print(f"- {category}: {counts['matched']}/{counts['expected']} matched")

    print("\n#### Matched benchmark items (sample)\n")
    if matches:
        for entry in matches[:12]:
            item = items[entry.benchmark_index]
            finding = findings[entry.finding_index]
            reason = entry.reason or (", ".join(entry.shared_tokens) if entry.shared_tokens else "(no reason provided)")
            reason = reason.replace('\n', ' ').strip()
            if len(reason) > 180:
                reason = reason[:177] + '...'
            print(
                f"- [{item.category}] {item.challenge} ⇄ {finding.finding_id} / {finding.title} "
                f"(score={entry.score}, judge={entry.endpoint_match}, reason={reason})"
            )
    else:
        print("- No benchmark items matched any current findings.")

    print("\n#### Top unmatched expected items (false negatives sample)\n")
    if unmatched_expected:
        for item in unmatched_expected[:15]:
            print(f"- [{item.automation}] [{item.category}] {item.challenge} — {item.endpoint}")
    else:
        print("- None.")

    print("\n#### Unmatched actual findings (false positives sample)\n")
    if unmatched_findings:
        for finding in unmatched_findings[:12]:
            print(f"- [{finding.severity}] {finding.finding_id} — {finding.title} ({finding.finding_type or 'type-unspecified'})")
    else:
        print("- None.")

    print("\n#### Notes\n")
    print("- This evaluator is intentionally benchmark-driven. It reads the expected list from a target-mapped markdown file and compares it against recorded findings; it does not contain Juice-Shop-specific scoring shortcuts or endpoint allowlists beyond what the benchmark file itself declares.")
    print("- Use automation_actionable_recall for the optimizer loop when reasoning about scanner quality, because the full benchmark includes many business-logic / OSINT / interactive items that a generic autonomous task runner should not be expected to solve reliably.")


if __name__ == "__main__":
    main()
