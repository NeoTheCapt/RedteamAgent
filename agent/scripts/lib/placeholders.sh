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

    # Surface candidates are advisory metadata. Preserve useful route shape when the
    # only unknown is a query value (for example `?forward=<encoded-url>` or
    # `?uuid=<profile.uuid>`), but continue rejecting unresolved path templates like
    # `/orders/<id>` that are too vague for coverage tracking.
    value="$(printf '%s' "$value" | perl -0pe '
        s/([?&][^=\s]+=)%3c[^\/%\s]+%3e/${1}.../ig;
        s/([?&][^=\s]+=)<[^>\s]+>/${1}.../g;
        s/([?&][^=\s]+=)\{\{[^}\s]+\}\}/${1}.../g;
        s/([?&][^=\s]+=)(FUZZ|PARAM)/${1}.../ig;
    ' )"

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
