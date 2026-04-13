#!/usr/bin/env bash

finding_prefix_for_agent() {
    local agent_name="${1:?agent name required}"

    case "$agent_name" in
        exploit-developer) printf '%s\n' "EX" ;;
        vulnerability-analyst) printf '%s\n' "VA" ;;
        source-analyzer) printf '%s\n' "SA" ;;
        recon-specialist) printf '%s\n' "RE" ;;
        fuzzer) printf '%s\n' "FZ" ;;
        osint-analyst) printf '%s\n' "OS" ;;
        *)
            echo "unknown finding prefix for agent: $agent_name" >&2
            return 1
            ;;
    esac
}

finding_lock_path() {
    local eng_dir="${1:?engagement dir required}"
    printf '%s\n' "$eng_dir/.finding-id.lock"
}

acquire_finding_lock() {
    local eng_dir="${1:?engagement dir required}"
    local lock_dir
    lock_dir="$(finding_lock_path "$eng_dir")"
    local attempts=0

    while ! mkdir "$lock_dir" 2>/dev/null; do
        attempts=$((attempts + 1))
        if [[ "$attempts" -ge 200 ]]; then
            echo "failed to acquire finding lock: $lock_dir" >&2
            return 1
        fi
        sleep 0.05
    done

    printf '%s\n' "$lock_dir"
}

release_finding_lock() {
    local lock_dir="${1:?lock dir required}"
    rmdir "$lock_dir" 2>/dev/null || true
}

next_finding_id() {
    local eng_dir="${1:?engagement dir required}"
    local agent_name="${2:?agent name required}"
    local findings_file="$eng_dir/findings.md"
    local prefix max_id next_num

    prefix="$(finding_prefix_for_agent "$agent_name")"
    max_id="$(
        rg --text -o "FINDING-${prefix}-[0-9]{3}" "$findings_file" 2>/dev/null \
            | sed "s/FINDING-${prefix}-//" \
            | tr -d '\r' \
            | awk '/^[0-9]+$/' \
            | sort -n \
            | tail -1
    )"
    max_id="${max_id:-0}"
    next_num=$((10#$max_id + 1))
    printf 'FINDING-%s-%03d\n' "$prefix" "$next_num"
}

update_finding_count() {
    local findings_file="${1:?findings file required}"
    local count tmp_file

    count="$(rg -c '^## \[FINDING-[A-Z]{2}-[0-9]{3}\]' "$findings_file" 2>/dev/null || printf '0')"
    tmp_file="$(mktemp "${TMPDIR:-/tmp}/findings-count.XXXXXX")"

    awk -v count="$count" '
        BEGIN { updated = 0 }
        /^\- \*\*Finding Count\*\*:/ {
            print "- **Finding Count**: " count
            updated = 1
            next
        }
        { print }
        END {
            if (!updated) {
                print ""
                print "- **Finding Count**: " count
            }
        }
    ' "$findings_file" >"$tmp_file"

    mv "$tmp_file" "$findings_file"
}

extract_finding_title() {
    local input_file="${1:?input file required}"

    sed -nE 's/^## \[(FINDING-ID|FINDING-[A-Z]{2}-[0-9]{3})\][[:space:]]+(.+)$/\2/p' "$input_file" | head -1
}

normalize_finding_title() {
    local raw_title="${1-}"

    printf '%s' "$raw_title" \
        | tr '[:upper:]' '[:lower:]' \
        | tr '\t' ' ' \
        | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
}

_findings_python_helpers() {
    cat <<'PY'
import difflib
import re
from urllib.parse import urlsplit


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def expand_identifier_breaks(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return re.sub(r"[_./-]+", " ", value)


def field_value(text: str, label: str) -> str:
    match = re.search(rf"(?mi)^- \*\*{re.escape(label)}\*\*:\s*(.+)$", text)
    return match.group(1).strip() if match else ""


def strip_wrapping(token: str) -> str:
    return token.strip().strip("`'\"<>[](){}.,;:")


def normalize_route(route: str) -> str:
    value = strip_wrapping(route)
    if not value:
        return ""

    method_match = re.match(r"(?i)^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+)$", value)
    if method_match:
        value = strip_wrapping(method_match.group(2))

    if value.startswith(("http://", "https://")):
        split = urlsplit(value)
        path = split.path or "/"
        if split.query:
            path += f"?{split.query}"
        return normalize_space(path)

    if value.startswith("/"):
        match = re.match(r"(/[^\s`\"'<>),;]+)", value)
        if match:
            return normalize_space(match.group(1))
        return normalize_space(value)

    return ""


def normalize_artifact_ref(value: str) -> str:
    token = strip_wrapping(value)
    if not token:
        return ""
    token = token.removeprefix("./")
    return normalize_space(token)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_routes(text: str) -> list[str]:
    candidates = [
        field_value(text, "Parameter"),
        field_value(text, "Target"),
        field_value(text, "Evidence"),
        field_value(text, "Evidence Ref"),
        text,
    ]

    method_url_pattern = re.compile(r"(?i)\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+((?:https?://|/)[^\s`\"'<>),;]+)")
    url_pattern = re.compile(r"https?://[^\s`\"'<>),;]+")
    path_pattern = re.compile(r"(?<![A-Za-z0-9:])(/[^\s`\"'<>),;]+)")

    routes: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        normalized = normalize_route(candidate)
        if normalized:
            routes.append(normalized)
        for match in method_url_pattern.finditer(candidate):
            normalized = normalize_route(f"{match.group(1).upper()} {match.group(2)}")
            if normalized:
                routes.append(normalized)
        for match in url_pattern.finditer(candidate):
            normalized = normalize_route(match.group(0))
            if normalized:
                routes.append(normalized)
        for match in path_pattern.finditer(candidate):
            normalized = normalize_route(match.group(1))
            if normalized:
                routes.append(normalized)

    return dedupe_preserve_order(routes)


def extract_route(text: str) -> str:
    routes = extract_routes(text)
    return routes[0] if routes else ""


def extract_artifact_ref(text: str) -> str:
    candidates = [
        field_value(text, "Evidence"),
        field_value(text, "Evidence Ref"),
        field_value(text, "Parameter"),
        field_value(text, "Target"),
        text,
    ]

    artifact_pattern = re.compile(
        r"(?<![A-Za-z0-9])((?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.(?:js|mjs|cjs|css|html|json|map|txt|md|wasm)(?:\.[A-Za-z0-9._-]+)*(?::\d+(?::\d+)?)?)"
    )

    for candidate in candidates:
        if not candidate:
            continue
        match = artifact_pattern.search(candidate)
        if not match:
            continue
        normalized = normalize_artifact_ref(match.group(1))
        if normalized:
            return normalized

    return ""


def split_findings(text: str):
    blocks = []
    current = []
    for line in text.splitlines():
        if re.match(r"^## \[FINDING-[A-Z]{2}-[0-9]{3}\]", line):
            if current:
                blocks.append("\n".join(current).strip() + "\n")
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip() + "\n")
    return blocks


def title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(a=left, b=right).ratio()


TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "api",
    "apis",
    "auth",
    "authentication",
    "authenticated",
    "callable",
    "endpoint",
    "endpoints",
    "exposes",
    "expose",
    "exposed",
    "for",
    "full",
    "get",
    "grants",
    "grant",
    "including",
    "is",
    "on",
    "post",
    "protected",
    "public",
    "response",
    "returns",
    "return",
    "route",
    "routes",
    "the",
    "to",
    "trigger",
    "triggers",
    "user",
    "with",
    "without",
}


def title_tokens(value: str) -> list[str]:
    if not value:
        return []

    normalized = normalize_space(expand_identifier_breaks(value))
    normalized = re.sub(r"[`'\"()\[\]{}:]+", " ", normalized)

    synonym_patterns = {
        r"\bunauthenticated\b": "missingauth",
        r"\bmissing authentication\b": "missingauth",
        r"\bwithout authentication\b": "missingauth",
        r"\bpasswords\b": "password",
        r"\bhashes\b": "hash",
        r"\btokens\b": "token",
        r"\baccepted\b": "accept",
        r"\baccepts\b": "accept",
        r"\bexpos(?:e|es|ed|ing)\b": "expose",
        r"\breturn(?:s|ed|ing)?\b": "return",
        r"\bgrant(?:s|ed|ing)?\b": "grant",
        r"\btriggers\b": "trigger",
    }
    for pattern, replacement in synonym_patterns.items():
        normalized = re.sub(pattern, replacement, normalized)

    tokens = []
    for token in re.findall(r"[a-z0-9]+", normalized):
        if len(token) <= 1 or token in TITLE_STOPWORDS:
            continue
        tokens.append(token)
    return dedupe_preserve_order(tokens)


def title_token_overlap(left: dict, right: dict) -> tuple[int, float]:
    left_tokens = set(left.get("title_tokens", []))
    right_tokens = set(right.get("title_tokens", []))
    if not left_tokens or not right_tokens:
        return (0, 0.0)
    overlap = left_tokens & right_tokens
    if not overlap:
        return (0, 0.0)
    score = len(overlap) / len(left_tokens | right_tokens)
    return (len(overlap), score)


def normalize_type_signature(value: str) -> str:
    if not value:
        return ""

    normalized = normalize_space(expand_identifier_breaks(value))
    normalized = re.sub(r"[`'\"()\[\]{}]+", " ", normalized)

    synonym_patterns = {
        r"\bvalidat(?:e|es|ed|ing|ion|ions)\b": "verify",
        r"\bverif(?:y|ies|ied|ying|ication|ications)\b": "verify",
        r"\bbypasses\b": "bypass",
        r"\bunauthenticated\b": "missingauth",
        r"\bmissing authentication\b": "missingauth",
        r"\bwithout authentication\b": "missingauth",
        r"\bexcessive data exposure\b": "data disclosure",
        r"\bsensitive data disclosure\b": "data disclosure",
        r"\binformation disclosure\b": "data disclosure",
    }
    for pattern, replacement in synonym_patterns.items():
        normalized = re.sub(pattern, replacement, normalized)

    ignored_tokens = {
        "abuse",
        "attack",
        "attacks",
        "endpoint",
        "fault",
        "handling",
        "input",
        "issue",
        "issues",
        "notification",
        "signature",
        "signal",
        "stateful",
        "trigger",
        "unprotected",
        "workflow",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and token not in ignored_tokens
    ]
    tokens = dedupe_preserve_order(tokens)
    if not tokens:
        return ""
    return " ".join(tokens)


def type_bucket(value: str) -> str:
    return normalize_type_signature(value)


def route_overlap(left: dict, right: dict) -> bool:
    return bool(set(left.get("routes", [])) & set(right.get("routes", [])))


def duplicate_reason(existing: dict, candidate: dict) -> str:
    if candidate["title_norm"] and existing["title_norm"] == candidate["title_norm"]:
        return "title"
    if (
        candidate["artifact_ref"]
        and candidate["type"]
        and existing["artifact_ref"] == candidate["artifact_ref"]
        and existing["type"] == candidate["type"]
    ):
        return "artifact+type"

    same_route = route_overlap(existing, candidate)
    same_severity = bool(candidate["severity"]) and existing["severity"] == candidate["severity"]
    same_owasp = bool(candidate["owasp"]) and existing["owasp"] == candidate["owasp"]
    same_type_bucket = bool(candidate["type_bucket"]) and existing["type_bucket"] == candidate["type_bucket"]
    title_overlap_count, title_overlap_score = title_token_overlap(existing, candidate)

    if same_route and same_severity and same_type_bucket:
        return "route+severity+type-bucket"
    if same_route and same_owasp and title_overlap_count >= 2 and title_overlap_score >= 0.45:
        return "route+owasp+title-token-overlap"
    if same_route and same_owasp and title_similarity(existing["title_norm"], candidate["title_norm"]) >= 0.65:
        return "route+owasp+title-similarity"
    return ""


def parse_finding(text: str) -> dict[str, object]:
    heading = re.search(r"(?m)^## \[(FINDING-[A-Z]{2}-[0-9]{3}|FINDING-ID)\]\s+(.+)$", text)
    finding_id = heading.group(1) if heading else ""
    title = heading.group(2) if heading else ""
    severity = normalize_space(field_value(text, "Severity"))
    owasp = normalize_space(field_value(text, "OWASP Category"))
    finding_type = normalize_space(field_value(text, "Type"))
    routes = extract_routes(text)
    return {
        "id": finding_id,
        "title": title,
        "title_norm": normalize_space(title),
        "title_tokens": title_tokens(title),
        "severity": severity,
        "owasp": owasp,
        "type": finding_type,
        "type_bucket": type_bucket(finding_type),
        "routes": routes,
        "route": routes[0] if routes else "",
        "artifact_ref": extract_artifact_ref(text),
    }
PY
}

find_existing_finding_id() {
    local findings_file="${1:?findings file required}"
    local candidate_file="${2:?candidate file required}"

    python3 - "$findings_file" "$candidate_file" <<PY
$( _findings_python_helpers )
import sys
from pathlib import Path

findings_path = Path(sys.argv[1])
candidate_path = Path(sys.argv[2])

candidate = parse_finding(candidate_path.read_text(encoding="utf-8"))
if not candidate["title_norm"] and not candidate["route"] and not candidate["artifact_ref"]:
    raise SystemExit(0)

for block in split_findings(findings_path.read_text(encoding="utf-8")):
    existing = parse_finding(block)
    if not existing["id"]:
        continue
    if duplicate_reason(existing, candidate):
        print(existing["id"])
        raise SystemExit(0)
PY
}

list_duplicate_finding_signatures() {
    local findings_file="${1:?findings file required}"

    python3 - "$findings_file" <<PY
$( _findings_python_helpers )
import sys
from pathlib import Path

path = Path(sys.argv[1])
findings = [
    parse_finding(block)
    for block in split_findings(path.read_text(encoding="utf-8"))
]

for index, finding in enumerate(findings):
    if not finding["id"]:
        continue
    for other in findings[index + 1 :]:
        if not other["id"]:
            continue
        reason = duplicate_reason(finding, other)
        if not reason:
            continue
        if reason == "artifact+type":
            print(
                f"{finding['id']} <-> {other['id']}: artifact={other['artifact_ref']} type={other['type']}"
            )
        elif reason.startswith("route+"):
            routes = sorted(set(finding.get("routes", [])) & set(other.get("routes", [])))
            joined = ", ".join(routes) if routes else other.get("route", "")
            print(
                f"{finding['id']} <-> {other['id']}: route={joined} reason={reason} title={other['title']}"
            )
        else:
            print(f"{finding['id']} <-> {other['id']}: title={other['title']}")
PY
}

replace_finding_placeholder() {
    local input_file="${1:?input file required}"
    local finding_id="${2:?finding id required}"
    local output_file="${3:?output file required}"

    awk -v finding_id="$finding_id" '
        BEGIN { replaced = 0 }
        {
            line = $0
            if (!replaced && line ~ /^## \[(FINDING-ID|FINDING-[A-Z]{2}-[0-9]{3})\]/) {
                sub(/\[(FINDING-ID|FINDING-[A-Z]{2}-[0-9]{3})\]/, "[" finding_id "]", line)
                replaced = 1
            }
            print line
        }
        END {
            if (!replaced) {
                exit 42
            }
        }
    ' "$input_file" >"$output_file"
}
