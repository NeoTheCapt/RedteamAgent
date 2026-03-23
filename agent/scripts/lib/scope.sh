#!/usr/bin/env bash

scope_entries() {
    local eng_dir="${1:?engagement dir required}"
    jq -r '([.hostname] + (.scope // [])) | map(select(type == "string" and . != "")) | unique[]' \
        "$eng_dir/scope.json" 2>/dev/null || true
}

extract_command_hosts() {
    local command="${1:-}"

    {
        printf '%s\n' "$command" | grep -oE '(https?://)?[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}(:[0-9]+)?' 2>/dev/null \
            | sed 's|https\?://||' | sed 's|:[0-9]*$||'
        printf '%s\n' "$command" | grep -oE '[0-9]{1,3}(\.[0-9]{1,3}){3}' 2>/dev/null
    } | sort -u
}

host_in_scope() {
    local host="${1:?host required}"
    shift
    local allowed wildcard_domain

    case "$host" in
        localhost|127.0.0.1|0.0.0.0|::1) return 0 ;;
    esac

    for allowed in "$@"; do
        [[ -n "$allowed" ]] || continue
        if [[ "$host" == "$allowed" ]]; then
            return 0
        fi
        wildcard_domain="${allowed#*.}"
        if [[ "$allowed" == "*."* ]]; then
            case "$host" in
                *".$wildcard_domain"|"$wildcard_domain") return 0 ;;
            esac
        fi
    done

    return 1
}

command_uses_raw_curl() {
    local command="${1:-}"

    [[ "$command" == *"run_tool curl"* ]] && return 1
    [[ "$command" == *"/engagement/tools/rtcurl"* ]] && return 1

    printf '%s\n' "$command" | grep -Eq '(^|[[:space:];|&(])(/usr/bin/curl|curl)([[:space:]]|$)'
}

command_hits_in_scope_target_with_raw_curl() {
    local eng_dir="${1:?engagement dir required}"
    local command="${2:-}"

    command_uses_raw_curl "$command" || return 1

    local -a scope_list=()
    while IFS= read -r item; do
        [[ -n "$item" ]] && scope_list+=("$item")
    done < <(scope_entries "$eng_dir")

    [[ "${#scope_list[@]}" -gt 0 ]] || return 1

    local host
    while IFS= read -r host; do
        [[ -n "$host" ]] || continue
        if host_in_scope "$host" "${scope_list[@]}"; then
            return 0
        fi
    done < <(extract_command_hosts "$command")

    return 1
}
