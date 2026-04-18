#!/usr/bin/env bash

KATANA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$KATANA_LIB_DIR/noise.sh"

katana_error_is_recoverable_discovery() {
    local error_text="${1:-}"
    [[ -n "$error_text" ]] || return 1

    case "$error_text" in
        *'hybrid: could not get dom'*|*'hybrid: response is nil'*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

katana_line_should_ingest() {
    local line="${1:-}"
    [[ -n "$line" ]] || return 1

    local error_text
    error_text="$(printf '%s' "$line" | jq -r '.error // empty' 2>/dev/null || true)"

    local url
    url="$(printf '%s' "$line" | jq -r '.request.endpoint // .request.url // .url // empty' 2>/dev/null || true)"

    if [[ -n "$error_text" ]]; then
        [[ -n "$url" ]] || return 1
        katana_error_is_recoverable_discovery "$error_text"
        return $?
    fi

    [[ -n "$url" ]] || printf '%s' "$line" | grep -qE '^https?://'
}

katana_request_should_ingest() {
    local request_json="${1:-}"
    [[ -n "$request_json" ]] || return 1

    local url url_path source_ref tag attribute content_type error_text response_status
    url="$(printf '%s' "$request_json" | jq -r '.url // empty' 2>/dev/null || true)"
    [[ -n "$url" ]] || return 1

    url_path="$(_katana_urlish_path "$url")"
    if is_katana_noise_path "$url_path"; then
        return 1
    fi

    source_ref="$(printf '%s' "$request_json" | jq -r '.source_ref // empty' 2>/dev/null || true)"
    tag="$(printf '%s' "$request_json" | jq -r '.tag // empty' 2>/dev/null || true)"
    attribute="$(printf '%s' "$request_json" | jq -r '.attribute // empty' 2>/dev/null || true)"
    content_type="$(printf '%s' "$request_json" | jq -r '.content_type // empty' 2>/dev/null || true)"
    error_text="$(printf '%s' "$request_json" | jq -r '.error // empty' 2>/dev/null || true)"
    response_status="$(printf '%s' "$request_json" | jq -r '.response_status // 0' 2>/dev/null || true)"

    if [[ -n "$error_text" ]] \
        && katana_error_is_recoverable_discovery "$error_text" \
        && [[ "$tag" == "html" ]] \
        && [[ "$attribute" == "regex" ]] \
        && is_katana_internal_source_path "$url_path"; then
        return 1
    fi

    # Regex-extracted API-like paths from JS are only trustworthy when the probe actually
    # lands on a viable endpoint. Real run 222 showed 401/500 responses from public bundle
    # regex matches getting queued as completed API cases, which polluted crawler-derived
    # coverage with low-signal routes like /rest/user/change-password?current=.
    # Treat any 4xx/5xx response here as a failed/bogus discovery and keep only successful
    # or otherwise undecided JS-derived API candidates.
    if [[ "$tag" == "js" ]] \
        && [[ "$attribute" == "regex" ]] \
        && is_katana_javascript_source_ref "$source_ref" \
        && is_katana_api_like_path "$url_path" \
        && [[ "$response_status" =~ ^[0-9]+$ ]] \
        && (( response_status >= 400 )); then
        return 1
    fi

    if is_katana_noise_source "$source_ref" "$tag" "$attribute" "$content_type" "$error_text"; then
        return 1
    fi

    return 0
}
