#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
                text_tokens=tokenize(corpus),
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
                        endpoint_candidates=extract_endpoint_candidates(endpoint),
                        text_tokens=tokenize(corpus),
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


def extract_endpoint_candidates(text: str) -> list[str]:
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
    return candidates


def endpoint_score(finding_eps: Iterable[str], benchmark_eps: Iterable[str]) -> tuple[int, str]:
    best_score = 0
    best_label = "none"
    for found in finding_eps:
        found_norm = normalize_endpoint(found)
        found_segments = {segment for segment in re.split(r"[/?&=]+", found_norm) if segment and segment not in {"{param}"}}
        for expected in benchmark_eps:
            expected_norm = normalize_endpoint(expected)
            expected_segments = {segment for segment in re.split(r"[/?&=]+", expected_norm) if segment and segment not in {"{param}"}}
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
    return best_score, best_label


def match_score(finding: Finding, item: BenchmarkItem) -> tuple[int, list[str], str]:
    shared = sorted((finding.text_tokens & item.text_tokens) & VULN_FAMILY_HINTS)
    ep_score, ep_label = endpoint_score(finding.endpoint_candidates, item.endpoint_candidates)
    family_overlap = len(shared)
    category_overlap = 1 if normalize_text(item.category) in normalize_text(finding.owasp_category + ' ' + finding.title + ' ' + finding.finding_type) else 0
    score = ep_score + min(family_overlap, 4) + category_overlap
    if any(token in finding.text_tokens for token in [item.category.lower(), item.challenge.lower()]):
        score += 1
    return score, shared, ep_label


def choose_matches(findings: list[Finding], items: list[BenchmarkItem]) -> list[Match]:
    candidates: list[Match] = []
    for f_idx, finding in enumerate(findings):
        for b_idx, item in enumerate(items):
            score, shared, ep_label = match_score(finding, item)
            if score >= 7 and (shared or ep_label != "none"):
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
    parser.add_argument("--root-dir", default="", help="Optional local-openclaw root for resolving relative benchmark paths.")
    parser.add_argument("--label", default="", help="Human label override.")
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
    matches = choose_matches(findings, items)

    matched_item_indexes = {entry.benchmark_index for entry in matches}
    matched_finding_indexes = {entry.finding_index for entry in matches}
    tp = len(matches)
    fp = max(len(findings) - tp, 0)
    fn = max(len(items) - tp, 0)
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = 0.0 if precision + recall == 0 else (2 * precision * recall / (precision + recall))

    automation_items = [index for index, item in enumerate(items) if coverage_bucket(item.automation) in {"high", "medium"}]
    automation_tp = sum(1 for index in automation_items if index in matched_item_indexes)
    automation_fn = len(automation_items) - automation_tp
    automation_recall = ratio(automation_tp, automation_tp + automation_fn)

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
    print("- matching_policy: conservative heuristic match on endpoint evidence + vulnerability-family token overlap (target-specific hardcoding disabled)")

    print("\n#### Category coverage\n")
    for category, counts in sorted(by_category.items(), key=lambda pair: (pair[0].lower(), pair[0])):
        print(f"- {category}: {counts['matched']}/{counts['expected']} matched")

    print("\n#### Matched benchmark items (sample)\n")
    if matches:
        for entry in matches[:12]:
            item = items[entry.benchmark_index]
            finding = findings[entry.finding_index]
            shared = ", ".join(entry.shared_tokens) if entry.shared_tokens else "(endpoint-only)"
            print(
                f"- [{item.category}] {item.challenge} ⇄ {finding.finding_id} / {finding.title} "
                f"(score={entry.score}, endpoint={entry.endpoint_match}, shared={shared})"
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
