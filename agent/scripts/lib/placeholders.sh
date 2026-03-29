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
