#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: append_surface_jsonl.sh <engagement_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPEND_SURFACE="$SCRIPT_DIR/append_surface.sh"

if [[ ! -x "$APPEND_SURFACE" ]]; then
    echo "ERROR: append_surface.sh not found or not executable" >&2
    exit 1
fi

normalize_surface_type() {
    local raw="${1:-}"
    raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
    case "$raw" in
        auth_entry|account_recovery|object_reference|privileged_write|file_handling|dynamic_render|api_documentation|workflow_token)
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
        auth|authentication|login|register|mfa)
            printf '%s\n' "auth_entry"
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

    if [[ "$haystack" == *"swagger"* || "$haystack" == *"openapi"* || "$haystack" == *"api doc"* || "$haystack" == *"documented"* || "$haystack" == *"/api-docs"* || "$haystack" == *"/okx-api"* || "$haystack" == *"docs-v5"* ]]; then
        printf '%s\n' "api_documentation"
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

invalid_lines=0
imported_lines=0

while IFS= read -r line; do
    [[ -n "$line" ]] || continue

    surface_type=$(printf '%s' "$line" | jq -r '.surface_type // .category // empty' 2>/dev/null || true)
    target=$(printf '%s' "$line" | jq -r '.target // empty' 2>/dev/null || true)
    source_name=$(printf '%s' "$line" | jq -r '.source // .agent // "operator-import"' 2>/dev/null || true)
    rationale=$(printf '%s' "$line" | jq -r '.rationale // .reason // .notes // empty' 2>/dev/null || true)
    evidence_ref=$(printf '%s' "$line" | jq -r '.evidence_ref // .evidence // ""' 2>/dev/null || true)
    status=$(printf '%s' "$line" | jq -r '.status // "discovered"' 2>/dev/null || true)
    method=$(printf '%s' "$line" | jq -r '.method // "GET"' 2>/dev/null || true)
    url_value=$(printf '%s' "$line" | jq -r '.url // .["url/path"] // .path // empty' 2>/dev/null || true)
    item_type=$(printf '%s' "$line" | jq -r '.type // empty' 2>/dev/null || true)
    auth_hint=$(printf '%s' "$line" | jq -r '.auth // empty' 2>/dev/null || true)

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

    if [[ -z "$normalized_type" || -z "$target" || -z "$source_name" || -z "$rationale" ]]; then
        echo "WARN: skipping invalid surface JSONL line" >&2
        invalid_lines=$((invalid_lines + 1))
        continue
    fi

    "$APPEND_SURFACE" "$ENG_DIR" "$normalized_type" "$target" "$source_name" "$rationale" "$evidence_ref" "$status"
    imported_lines=$((imported_lines + 1))
done

if (( invalid_lines > 0 )); then
    echo "WARN: skipped $invalid_lines invalid surface JSONL line(s)" >&2
fi

if (( imported_lines == 0 && invalid_lines > 0 )); then
    exit 1
fi
