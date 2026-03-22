#!/usr/bin/env bash
set -euo pipefail

AUTH_FILE="${RTCURL_AUTH_FILE:-/engagement/auth.json}"
SCOPE_FILE="${RTCURL_SCOPE_FILE:-/engagement/scope.json}"

debug() {
    if [[ "${RTCURL_DEBUG:-0}" == "1" ]]; then
        echo "[rtcurl] $*" >&2
    fi
}

extract_urls() {
    local args=("$@")
    local i=0
    local arg next
    while (( i < ${#args[@]} )); do
        arg="${args[$i]}"
        next="${args[$((i + 1))]:-}"
        case "$arg" in
            --url)
                [[ -n "$next" ]] && printf '%s\n' "$next"
                ((i += 2))
                continue
                ;;
            --url=*)
                printf '%s\n' "${arg#--url=}"
                ((i += 1))
                continue
                ;;
            http://*|https://*)
                printf '%s\n' "$arg"
                ;;
        esac
        ((i += 1))
    done
}

extract_host() {
    local url="$1"
    local rest hostport host
    rest="${url#http://}"
    rest="${rest#https://}"
    rest="${rest#*@}"
    hostport="${rest%%[/?#]*}"

    if [[ "$hostport" == \[*\]* ]]; then
        host="${hostport%%]*}"
        host="${host#[}"
    else
        host="${hostport%%:*}"
    fi

    printf '%s\n' "$host" | tr '[:upper:]' '[:lower:]'
}

host_in_scope() {
    local host="$1"
    local entry suffix

    while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        entry="$(printf '%s' "$entry" | tr '[:upper:]' '[:lower:]')"
        if [[ "$entry" == \*.* ]]; then
            suffix="${entry#*.}"
            if [[ "$host" == "$suffix" || "$host" == *".${suffix}" ]]; then
                return 0
            fi
        elif [[ "$host" == "$entry" ]]; then
            return 0
        fi
    done < <(jq -r '([.hostname] + (.scope // [])) | map(select(type == "string" and . != "")) | unique[]' "$SCOPE_FILE" 2>/dev/null)

    return 1
}

collect_explicit_auth_overrides() {
    local args=("$@")
    local i=0
    local arg next header_name lower

    EXPLICIT_COOKIE=0
    EXPLICIT_LOCATION=0
    EXPLICIT_HEADERS=()

    while (( i < ${#args[@]} )); do
        arg="${args[$i]}"
        next="${args[$((i + 1))]:-}"
        case "$arg" in
            -H|--header)
                if [[ -n "$next" ]]; then
                    header_name="${next%%:*}"
                    lower="$(printf '%s' "$header_name" | tr '[:upper:]' '[:lower:]')"
                    EXPLICIT_HEADERS+=("$lower")
                    [[ "$lower" == "cookie" ]] && EXPLICIT_COOKIE=1
                    ((i += 2))
                    continue
                fi
                ;;
            --header=*)
                header_name="${arg#--header=}"
                header_name="${header_name%%:*}"
                lower="$(printf '%s' "$header_name" | tr '[:upper:]' '[:lower:]')"
                EXPLICIT_HEADERS+=("$lower")
                [[ "$lower" == "cookie" ]] && EXPLICIT_COOKIE=1
                ;;
            -b|--cookie)
                EXPLICIT_COOKIE=1
                ((i += 2))
                continue
                ;;
            --cookie=*)
                EXPLICIT_COOKIE=1
                ;;
            -L|--location|--location-trusted)
                EXPLICIT_LOCATION=1
                ;;
        esac
        ((i += 1))
    done
}

has_explicit_header() {
    local needle="$1"
    local item
    for item in "${EXPLICIT_HEADERS[@]:-}"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

build_auth_args() {
    local cookie_header key value
    RTCURL_ARGS=()

    [[ -f "$AUTH_FILE" ]] || return 0

    if (( EXPLICIT_LOCATION )); then
        debug "location flag detected; skipping automatic auth injection"
        return 0
    fi

    if ! (( EXPLICIT_COOKIE )) && ! has_explicit_header "cookie"; then
        cookie_header="$(jq -r '
            if (.cookies | type) == "object" and ((.cookies | keys | length) > 0)
            then "Cookie: " + (.cookies | to_entries | map(.key + "=" + .value) | join("; "))
            else empty end
        ' "$AUTH_FILE" 2>/dev/null)"
        if [[ -n "$cookie_header" ]]; then
            RTCURL_ARGS+=("-H" "$cookie_header")
        fi
    fi

    while IFS=$'\t' read -r key value; do
        [[ -n "$key" ]] || continue
        if has_explicit_header "$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"; then
            continue
        fi
        RTCURL_ARGS+=("-H" "${key}: ${value}")
    done < <(jq -r '
        if (.headers | type) == "object"
        then .headers | to_entries[] | [.key, .value] | @tsv
        else empty end
    ' "$AUTH_FILE" 2>/dev/null)
}

main() {
    local args=("$@")
    local urls=()
    local url host
    local in_scope=1

    collect_explicit_auth_overrides "${args[@]}"

    if [[ ! -f "$SCOPE_FILE" ]]; then
        debug "scope file missing; exec raw curl"
        exec curl "${args[@]}"
    fi

    while IFS= read -r url; do
        [[ -n "$url" ]] || continue
        urls+=("$url")
    done < <(extract_urls "${args[@]}")

    if (( ${#urls[@]} == 0 )); then
        debug "no target URL found; exec raw curl"
        exec curl "${args[@]}"
    fi

    for url in "${urls[@]}"; do
        host="$(extract_host "$url")"
        if [[ -z "$host" ]] || ! host_in_scope "$host"; then
            in_scope=0
            debug "target outside scope: $url"
            break
        fi
    done

    if (( in_scope )); then
        build_auth_args
        debug "injecting ${#RTCURL_ARGS[@]} auth args for in-scope target(s)"
        if (( ${#RTCURL_ARGS[@]} > 0 )); then
            exec curl "${RTCURL_ARGS[@]}" "${args[@]}"
        fi
        exec curl "${args[@]}"
    fi

    exec curl "${args[@]}"
}

main "$@"
