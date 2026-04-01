#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: append_surface_jsonl.sh <engagement_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/placeholders.sh"
APPEND_SURFACE="$SCRIPT_DIR/append_surface.sh"

if [[ ! -x "$APPEND_SURFACE" ]]; then
    echo "ERROR: append_surface.sh not found or not executable" >&2
    exit 1
fi

normalize_surface_type() {
    local raw="${1:-}"
    raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
    case "$raw" in
        auth_entry|account_recovery|object_reference|privileged_write|file_handling|dynamic_render|api_documentation|workflow_token|api_param_followup|cors_review)
            printf '%s\n' "$raw"
            return 0
            ;;
        auth_workflow)
            printf '%s\n' "account_recovery"
            return 0
            ;;
        identity_verification)
            printf '%s\n' "auth_entry"
            return 0
            ;;
        p2p_trading|web3_assets|preview_or_internal_content)
            printf '%s\n' "dynamic_render"
            return 0
            ;;
        file|upload)
            printf '%s\n' "file_handling"
            return 0
            ;;
        api_docs|swagger|openapi)
            printf '%s\n' "api_documentation"
            return 0
            ;;
        spa_route|spa|client_route|client_side_route|frontend_route)
            printf '%s\n' "dynamic_render"
            return 0
            ;;
        asset_distribution|cdn_asset_host|cdn_host|download_host|object_storage|storage_bucket)
            printf '%s\n' "dynamic_render"
            return 0
            ;;
        auth|authentication|login|register|mfa|oauth|oauth_flow|auth_surface)
            printf '%s\n' "auth_entry"
            return 0
            ;;
        business_logic|logic_flow|stateful_flow|race_condition|authenticated_admin_api|authenticated_api)
            printf '%s\n' "privileged_write"
            return 0
            ;;
        update_distribution|distribution_artifact)
            printf '%s\n' "file_handling"
            return 0
            ;;
        cors_surface)
            printf '%s\n' "cors_review"
            return 0
            ;;
        opaque_post_contract|opaque_post_body|body_contract|schema_followup|reflected_input)
            printf '%s\n' "api_param_followup"
            return 0
            ;;
        admin_session)
            printf '%s\n' "workflow_token"
            return 0
            ;;
        "")
            return 1
            ;;
        *)
            return 1
            ;;
    esac
}

infer_surface_type() {
    local method="${1:-}"
    local target="${2:-}"
    local item_type="${3:-}"
    local auth_hint="${4:-}"
    local rationale="${5:-}"
    local haystack

    haystack="$(printf '%s %s %s %s %s' "$method" "$target" "$item_type" "$auth_hint" "$rationale" | tr '[:upper:]' '[:lower:]')"

    if [[ "$item_type" == "file" || "$haystack" == *"kdbx"* || "$haystack" == *"/ftp/"* || "$haystack" == *"file-upload"* ]]; then
        printf '%s\n' "file_handling"
        return 0
    fi

    if [[ "$haystack" == *"swagger"* || "$haystack" == *"openapi"* || "$haystack" == *"api doc"* || "$haystack" == *"documented"* || "$haystack" == *"/api-docs"* || "$haystack" == *"/api-v5"* || "$haystack" == *"docs-api"* ]]; then
        printf '%s\n' "api_documentation"
        return 0
    fi

    if [[ "$item_type" == "asset-distribution" || "$item_type" == "asset_distribution" || "$item_type" == "cdn-asset-host" || "$item_type" == "cdn_asset_host" || "$item_type" == "cdn-host" || "$item_type" == "object-storage" || "$item_type" == "storage-bucket" || "$haystack" == *"asset host"* || "$haystack" == *"cdn host"* || "$haystack" == *"installer manifest"* || "$haystack" == *"object storage"* ]]; then
        printf '%s\n' "dynamic_render"
        return 0
    fi

    if [[ "$haystack" == *"forgot-password"* || "$haystack" == *"reset-password"* || "$haystack" == *"security-question"* || "$haystack" == *"account recovery"* || "$haystack" == *"password reset"* ]]; then
        printf '%s\n' "account_recovery"
        return 0
    fi

    if [[ "$haystack" == *"change-password"* || "$haystack" == *"privileged"* ]]; then
        printf '%s\n' "privileged_write"
        return 0
    fi

    if [[ "$haystack" == *"2fa"* || "$haystack" == *"totp"* || "$haystack" == *"otp"* || "$haystack" == *"token"* || "$haystack" == *"jwt"* || "$haystack" == *"session"* || "$haystack" == *"cookie"* || "$haystack" == *"workflow"* ]]; then
        printf '%s\n' "workflow_token"
        return 0
    fi

    if [[ "$haystack" == *"object"* || "$haystack" == *"idor"* || "$haystack" == *"{id}"* || "$haystack" == *"/track-order/"* || "$haystack" == *"orderid"* ]]; then
        printf '%s\n' "object_reference"
        return 0
    fi

    if [[ "$method" != "GET" && "$item_type" == "api" ]]; then
        printf '%s\n' "privileged_write"
        return 0
    fi

    if [[ "$haystack" == *"login"* || "$haystack" == *"register"* || "$haystack" == *"auth"* || "$haystack" == *"mfa"* ]]; then
        printf '%s\n' "auth_entry"
        return 0
    fi

    if [[ "$item_type" == "page" ]]; then
        printf '%s\n' "dynamic_render"
        return 0
    fi

    if [[ -z "$item_type" && "$method" == "GET" && "$target" == GET\ /* ]]; then
        if [[ "$target" != GET\ /api* && "$target" != GET\ /v[0-9]* && "$target" != GET\ /priapi* && "$target" != GET\ /rest/* && "$target" != GET\ /*.* ]]; then
            printf '%s\n' "dynamic_render"
            return 0
        fi
    fi

    return 1
}

extract_surface_locator() {
    local text="${1:-}"
    [[ -n "$text" ]] || return 1

    python3 - "$text" <<'PY'
import re
import sys

text = sys.argv[1]
candidates = []
patterns = [
    r"https?://[^\s\"'<>`]+",
    r"/(?:[A-Za-z0-9._~!$&'()*+,;=:@%-]+/?)+(?:\?[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?",
]
for pattern in patterns:
    candidates.extend(re.findall(pattern, text))

seen = set()
ordered = []
for candidate in candidates:
    if candidate in seen:
        continue
    seen.add(candidate)
    ordered.append(candidate)

preferred_markers = (
    "/rest/",
    "/api",
    "/graphql",
    "/file-upload",
    "/2fa/",
    "/login",
    "/security-question",
    "/reset-password",
    "/swagger",
    "/api-docs",
)
ignored_exact = {"/verify", "/spec", "/decal"}


def score(value: str) -> int:
    lower = value.lower()
    score_value = 80 if lower.startswith("http") else 30
    if any(marker in lower for marker in preferred_markers):
        score_value += 50
    if lower in ignored_exact:
        score_value -= 100
    if lower.startswith(("/downloads/", "/scans/", "/assets/")):
        score_value -= 80
    if re.search(r"\.(js|css|png|jpg|jpeg|gif|svg|map|html|md|txt)([:?]|$)", lower):
        score_value -= 60
    if ":" in lower and not lower.startswith("http"):
        score_value -= 40
    if lower.count("/") <= 1 and not lower.startswith("/api") and not lower.startswith("/rest/"):
        score_value -= 30
    return score_value

ranked = sorted(((score(candidate), candidate) for candidate in ordered), reverse=True)
for score_value, candidate in ranked:
    if score_value > 0:
        print(candidate)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

fallback_surface_target() {
    local normalized_type="${1:-}"
    case "$normalized_type" in
        dynamic_render)
            printf '%s\n' "GET /"
            ;;
        api_documentation)
            printf '%s\n' "GET /api-docs"
            ;;
        *)
            return 1
            ;;
    esac
}

synthesize_surface_target() {
    local normalized_type="${1:-}"
    local method="${2:-GET}"
    local url_value="${3:-}"
    local next_action="${4:-}"
    local evidence_ref="${5:-}"
    local rationale="${6:-}"
    local locator=""

    if [[ -n "$url_value" ]]; then
        locator="$url_value"
    else
        for hint in "$next_action" "$evidence_ref" "$rationale"; do
            if locator="$(extract_surface_locator "$hint" 2>/dev/null)"; then
                break
            fi
        done
    fi

    if [[ -n "$locator" ]]; then
        printf '%s\n' "$method $locator"
        return 0
    fi

    fallback_surface_target "$normalized_type"
}

build_surface_rationale() {
    local raw_rationale="${1:-}"
    local evidence_text="${2:-}"
    local next_action="${3:-}"
    local rationale="$raw_rationale"

    if [[ -z "$rationale" ]]; then
        if [[ -n "$evidence_text" && -n "$next_action" ]]; then
            rationale="$evidence_text Next action: $next_action"
        elif [[ -n "$evidence_text" ]]; then
            rationale="$evidence_text"
        else
            rationale="$next_action"
        fi
    elif [[ -n "$next_action" && "$rationale" != *"$next_action"* ]]; then
        rationale="$rationale Next action: $next_action"
    fi

    printf '%s\n' "$rationale"
}

invalid_lines=0
imported_lines=0

while IFS= read -r line; do
    [[ -n "$line" ]] || continue

    surface_type=$(printf '%s' "$line" | jq -r '.surface_type // .category // empty' 2>/dev/null || true)
    target=$(printf '%s' "$line" | jq -r '.target // empty' 2>/dev/null || true)
    source_name=$(printf '%s' "$line" | jq -r '.source // .agent // "operator-import"' 2>/dev/null || true)
    raw_rationale=$(printf '%s' "$line" | jq -r '.rationale // .reason // .notes // empty' 2>/dev/null || true)
    evidence_ref=$(printf '%s' "$line" | jq -r '.evidence_ref // .evidence // ""' 2>/dev/null || true)
    evidence_text=$(printf '%s' "$line" | jq -r '.evidence // .evidence_ref // ""' 2>/dev/null || true)
    next_action=$(printf '%s' "$line" | jq -r '.next_action // .nextAction // empty' 2>/dev/null || true)
    status=$(printf '%s' "$line" | jq -r '.status // "discovered"' 2>/dev/null || true)
    method=$(printf '%s' "$line" | jq -r '.method // "GET"' 2>/dev/null || true)
    url_value=$(printf '%s' "$line" | jq -r '.url // .["url/path"] // .path // .url_or_pattern // .urlOrPattern // empty' 2>/dev/null || true)
    item_type=$(printf '%s' "$line" | jq -r '.type // empty' 2>/dev/null || true)
    auth_hint=$(printf '%s' "$line" | jq -r '.auth // empty' 2>/dev/null || true)

    rationale="$(build_surface_rationale "$raw_rationale" "$evidence_text" "$next_action")"

    if [[ -z "$target" && -n "$url_value" ]]; then
        target="$url_value"
        if [[ -n "$method" ]]; then
            target="$method $target"
        fi
    fi

    if ! normalized_type="$(normalize_surface_type "$surface_type")"; then
        if ! normalized_type="$(infer_surface_type "$method" "$target" "$item_type" "$auth_hint" "$rationale")"; then
            normalized_type=""
        fi
    fi

    if [[ -z "$target" ]]; then
        target="$(synthesize_surface_target "$normalized_type" "$method" "$url_value" "$next_action" "$evidence_ref" "$rationale" 2>/dev/null || true)"
    fi

    target="$(normalize_surface_placeholder_target "$target")"

    if [[ -z "$normalized_type" || -z "$target" || -z "$source_name" || -z "$rationale" ]]; then
        echo "WARN: skipping invalid surface JSONL line" >&2
        invalid_lines=$((invalid_lines + 1))
        continue
    fi

    if contains_surface_placeholder "$target"; then
        echo "WARN: skipping unresolved placeholder surface target: $target" >&2
        invalid_lines=$((invalid_lines + 1))
        continue
    fi

    "$APPEND_SURFACE" "$ENG_DIR" "$normalized_type" "$target" "$source_name" "$rationale" "$evidence_ref" "$status"
    imported_lines=$((imported_lines + 1))
done

if (( invalid_lines > 0 )); then
    echo "WARN: skipped $invalid_lines invalid surface JSONL line(s)" >&2
fi

# Surface candidates are advisory metadata, not queue-critical state.
# If an agent returns only unresolved placeholder targets, warn but do not
# abort the parent operator step — otherwise cases can be left stuck in
# `processing` even though the actionable findings/case outcomes were valid.
# Callers that need stricter validation should pre-validate their JSONL.
true
