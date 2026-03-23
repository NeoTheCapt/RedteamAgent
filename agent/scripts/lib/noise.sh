#!/usr/bin/env bash

is_katana_noise_path() {
    local path="${1:-}"
    local path_lower
    path_lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"

    [[ -z "$path" ]] && return 0

    if printf '%s' "$path_lower" | grep -qiE '(\{\{|\}\}|%7b%7b|%7d%7d|'"'"'\+|\+'"'"'|"\\\+|\+")'; then
        return 0
    fi

    case "$path_lower" in
        /application/vnd.*|/text/*|/audio/*|/video/*|/image/*|/font/*)
            return 0
            ;;
    esac

    case "$path_lower" in
        /edge/|/trident/|/-)
            return 0
            ;;
    esac

    return 1
}
