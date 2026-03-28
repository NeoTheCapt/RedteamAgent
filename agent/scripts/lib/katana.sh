#!/usr/bin/env bash

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
