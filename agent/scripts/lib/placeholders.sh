#!/usr/bin/env bash

contains_surface_placeholder() {
    local value="${1:-}"
    [[ -n "$value" ]] || return 1
    printf '%s' "$value" | grep -qiE '(%3c[^/%[:space:]]+%3e|<[^>[:space:]]+>|FUZZ|PARAM|\{\{|\}\})'
}

contains_queue_placeholder() {
    local value="${1:-}"
    [[ -n "$value" ]] || return 1
    printf '%s' "$value" | grep -qiE '(%3c[^/%[:space:]]+%3e|%7b|%7d|<[^>[:space:]]+>|FUZZ|PARAM|\{\{|\}\}|\*|\{|\})'
}

normalize_surface_placeholder_target() {
    local value="${1:-}"
    local method_count

    printf '%s' "$value" >/dev/null
    if ! contains_surface_placeholder "$value"; then
        printf '%s' "$value"
        return 0
    fi

    method_count="$(printf '%s' "$value" | grep -Eoi '\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b' | wc -l | tr -d '[:space:]')"
    if [[ -z "$method_count" || "$method_count" -lt 2 ]]; then
        printf '%s' "$value"
        return 0
    fi

    printf '%s' "$value" | perl -0pe 's/%3c[^\/%\s]+%3e/.../ig; s/<[^>\s]+>/.../g'
}
