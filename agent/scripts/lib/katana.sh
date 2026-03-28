#!/usr/bin/env bash

katana_line_should_ingest() {
    local line="${1:-}"
    [[ -n "$line" ]] || return 1

    local error_text
    error_text="$(printf '%s' "$line" | jq -r '.error // empty' 2>/dev/null || true)"
    [[ -z "$error_text" ]] || return 1

    local url
    url="$(printf '%s' "$line" | jq -r '.request.endpoint // .request.url // .url // empty' 2>/dev/null || true)"
    [[ -n "$url" ]] || printf '%s' "$line" | grep -qE '^https?://'
}
