#!/usr/bin/env bash

katana_emit_out_of_scope_regexes() {
    cat <<'EOF'
https?://[^?#]*(?:%5[cC]|\\|%22|"|%27|'|\{\{|\}\}|%7[bB]%7[bB]|%7[dD]%7[dD]|%2[aA]|\*)
https?://[^?#]+/(?:assets|cdn/assets|cdnpre/assets|cdn/i18n)/(?:[^?#]*/)?(?:images?|img|icons?|fonts?|i18n)(?:/[^?#]*)?(?:$|[?#])
https?://[^?#]+/(?:assets|cdn/assets|cdnpre/assets|cdn/i18n)/(?:[^?#]*/)?(?:assets|cdn/assets|cdnpre/assets|cdn/i18n)/(?:[^?#]*)?(?:$|[?#])
https?://[^?#]+/(?:assets|cdn/assets|cdnpre/assets)/(?:[^?#]*/)?(?:scripts/lib|[bB]un)(?:/[^?#]*)?(?:$|[?#])
https?://[^?#]+/(?:[^?#]*/)?(?:[Tt]rident|[Ee]dge)(?:/[^?#]*)?(?:$|[?#])
https?://[^?#]+/(?:[^?#]*/)?(?:build/routes|node_modules)(?:/[^?#]*)?(?:$|[?#])
https?://[^?#]+/\.well-known/[^?#]+/[0-9]{2,5}/\.well-known/[^?#]+(?:/[^?#]*)?(?:$|[?#])
https?://[^?#]+\.(?:png|jpe?g|gif|webp|bmp|ico|svg|avif|mp3|mp4|wav|ogg|pdf|zip|gz|woff2?|ttf|eot|wasm(?:\.br|\.gz)?)(?:$|[?#])
EOF
}

_katana_urlish_path() {
    local value="${1:-}"
    value="${value#*://}"
    value="/${value#*/}"
    value="${value%%\?*}"
    value="${value%%\#*}"
    [[ -n "$value" ]] || value="/"
    printf '%s\n' "$value"
}

is_katana_binary_source_ref() {
    local source_ref="${1:-}"
    local source_path
    source_path="$(_katana_urlish_path "$source_ref")"
    source_path="$(printf '%s' "$source_path" | tr '[:upper:]' '[:lower:]')"

    case "$source_path" in
        *.png|*.jpg|*.jpeg|*.gif|*.webp|*.bmp|*.ico|*.svg|*.avif|*.mp3|*.mp4|*.wav|*.ogg|*.pdf|*.zip|*.gz|*.woff|*.woff2|*.ttf|*.eot|*.wasm|*.wasm.br|*.wasm.gz)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_katana_internal_source_path() {
    local path="${1:-}"
    local path_lower
    path_lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"

    case "$path_lower" in
        */build/routes/*|*/node_modules/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_katana_javascript_source_ref() {
    local source_ref="${1:-}"
    local source_path
    source_path="$(_katana_urlish_path "$source_ref")"
    source_path="$(printf '%s' "$source_path" | tr '[:upper:]' '[:lower:]')"

    case "$source_path" in
        *.js|*.mjs|*.cjs|*.jsx|*.js.map|*.mjs.map|*.cjs.map|*.jsx.map)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_katana_api_like_path() {
    local path="${1:-}"
    local path_lower
    path_lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"

    case "$path_lower" in
        /api/*|/rest/*|/graphql*|/graphiql*|/priapi/*|/v[0-9]/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_katana_low_signal_realtime_url() {
    local url="${1:-}"
    local path_lower query_lower

    [[ -n "$url" ]] || return 1

    path_lower="$(_katana_urlish_path "$url")"
    path_lower="$(printf '%s' "$path_lower" | tr '[:upper:]' '[:lower:]')"
    query_lower=""
    if [[ "$url" == *\?* ]]; then
        query_lower="${url#*\?}"
        query_lower="$(printf '%s' "$query_lower" | tr '[:upper:]' '[:lower:]')"
    fi

    case "$path_lower" in
        /socket.io|/socket.io/)
            if [[ "$query_lower" == *"transport=polling"* ]]; then
                return 0
            fi
            ;;
    esac

    return 1
}

is_katana_noise_source() {
    local source_ref="${1:-}"
    local _tag="${2:-}"
    local _attribute="${3:-}"
    local _content_type="${4:-}"
    local _error_text="${5:-}"

    [[ -n "$source_ref" ]] || return 1

    if is_katana_binary_source_ref "$source_ref"; then
        return 0
    fi

    # Treat asset-directory source pages as noise too. Some SPA targets serve index.html
    # for arbitrary asset subpaths (for example /assets/.../), which makes katana emit
    # recoverable error discoveries for bogus relative .js/.css links under those paths.
    # Those rows have no trustworthy response metadata and poison the crawl queue.
    local source_path
    source_path="$(_katana_urlish_path "$source_ref")"
    if is_katana_noise_path "$source_path" || is_katana_internal_source_path "$source_path"; then
        return 0
    fi

    return 1
}

is_katana_noise_path() {
    local path="${1:-}"
    local path_lower
    path_lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"

    [[ -z "$path" ]] && return 0

    if printf '%s' "$path_lower" | grep -qiE "(%5c|\\\\|%22|\"|\{\{|\}\}|%7b%7b|%7d%7d|%2a|\*|'\+|\+'|\"\\\+|\+\")"; then
        return 0
    fi

    case "$path_lower" in
        *'$')
            return 0
            ;;
    esac

    case "$path_lower" in
        /application/vnd.*|/text/*|/audio/*|/video/*|/image/*|/font/*)
            return 0
            ;;
    esac

    case "$path_lower" in
        /assets/*/|/cdn/assets/*/|/cdnpre/assets/*/|/cdn/i18n/*/)
            return 0
            ;;
        /assets/*/images/*|/assets/*/img/*|/assets/*/icons/*|/assets/*/fonts/*|/assets/i18n/*|*/assets/public/assets/public/*)
            return 0
            ;;
        /cdn/assets/*/images/*|/cdn/assets/*/img/*|/cdn/assets/*/icons/*|/cdn/assets/*/fonts/*|/cdnpre/assets/*/images/*|/cdnpre/assets/*/img/*|/cdnpre/assets/*/icons/*|/cdnpre/assets/*/fonts/*|/cdn/i18n/*|*/assets/i18n/assets/public/*)
            return 0
            ;;
    esac

    case "$path_lower" in
        /edge/|/trident/|/edge/*|/trident/*|/-)
            return 0
            ;;
    esac

    if printf '%s' "$path_lower" | grep -Eq '/\.well-known/[^/]+/[0-9]{2,5}/\.well-known/[^/]+'; then
        return 0
    fi

    return 1
}
