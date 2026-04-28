#!/usr/bin/env bash
# source_queue_filter.sh — Heuristics for suppressing low-signal source-analyzer
# queue growth while preserving high-value auth/API follow-up coverage.

_source_queue_lower() {
    printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

_source_queue_path() {
    local url_path="${1:-}"
    local url="${2:-}"
    if [[ -n "$url_path" && "$url_path" != "null" ]]; then
        printf '%s' "$url_path"
        return 0
    fi
    printf '%s' "$url" | sed -E 's#^[a-z]+://[^/]+##I' | sed -E 's/[?#].*$//'
}

_source_queue_is_high_signal_page() {
    local path_lower="$(_source_queue_lower "$1")"

    [[ "$path_lower" =~ (^|/)(account|auth|login|register|signin|signup|logout)(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(forgot|forget|reset|recover|recovery|security-reset|security|verify|verification|mfa|otp|2fa|protect|security-assistant)(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(redirect|redirector|redir|bounce|goto|jump|out|away)(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)support-center/channel-verification(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(broker|sub-account|subaccount|oauth|wallet|watchlist|trade|asset|defi)(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(docs-v[0-9]+|api-docs?|swagger|openapi)(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(status|health|captcha)(/|$) ]] && return 0
    [[ "$path_lower" =~ ^/(ftp|downloads?|downloads-public|artifacts?|assets?|backups?|exports?|dumps?|files?)(/|$) ]] && return 0
    return 1
}

_source_queue_is_repo_artifact_path() {
    local path_lower="$(_source_queue_lower "$1")"
    [[ "$path_lower" =~ ^/(ftp|downloads?|downloads-public|artifacts?|assets?|backups?|exports?|dumps?|files?)(/|$) ]]
}

_source_queue_has_sensitive_doc_keyword() {
    local value_lower="$(_source_queue_lower "$1")"
    [[ "$value_lower" =~ (auth|credential|secret|token|password|passwd|key|config|settings|backup|dump|export|incident|security|admin|account|wallet|payment|invoice|access|recover|reset|support) ]]
}

_source_queue_is_high_signal_repo_artifact() {
    local path_lower="$(_source_queue_lower "$1")"
    local basename_lower="${path_lower##*/}"
    local stem_lower="$basename_lower"

    # Strip one layer of backup-ish wrapper suffix so `config.json.bak` still
    # evaluates like the underlying structured artifact, while `notes.md.bak`
    # can still be suppressed as low-yield prose.
    stem_lower="${stem_lower%.bak}"
    stem_lower="${stem_lower%.backup}"
    stem_lower="${stem_lower%.old}"
    stem_lower="${stem_lower%.orig}"
    stem_lower="${stem_lower%.save}"
    stem_lower="${stem_lower%.swp}"
    stem_lower="${stem_lower%.tmp}"

    [[ "$basename_lower" =~ \.(kdbx|sqlite|db|sql|dump|ya?ml|toml|ini|cfg|conf|env|pem|key|crt|cer|p12|pfx|ovpn|ppk|plist|json)(\.|$) ]] && return 0
    [[ "$basename_lower" =~ \.(zip|tar|tgz|gz|bz2|xz|7z|rar)(\.|$) ]] && return 0
    [[ "$basename_lower" =~ \.(bak|backup|old|orig|save|swp|tmp)(\.|$) ]] && [[ "$stem_lower" =~ \.(json|ya?ml|toml|ini|cfg|conf|env|sql|db|sqlite|kdbx|pem|key|crt|cer|p12|pfx|ovpn|ppk|plist)(\.|$) ]] && return 0

    if [[ "$basename_lower" =~ \.(md|markdown|txt|text|csv|tsv|url|webloc|rtf|doc|docx|pdf)(\.|$) ]]; then
        _source_queue_has_sensitive_doc_keyword "$basename_lower"
        return $?
    fi

    if [[ "$basename_lower" =~ \.(bak|backup|old|orig|save|swp|tmp)(\.|$) ]]; then
        if [[ "$stem_lower" =~ \.(md|markdown|txt|text|csv|tsv|url|webloc|rtf|doc|docx|pdf)(\.|$) ]]; then
            _source_queue_has_sensitive_doc_keyword "$stem_lower"
            return $?
        fi
        _source_queue_has_sensitive_doc_keyword "$stem_lower"
        return $?
    fi

    _source_queue_has_sensitive_doc_keyword "$basename_lower"
    return $?
}

_source_queue_is_high_signal_data() {
    local path_lower="$(_source_queue_lower "$1")"

    [[ "$path_lower" == "/robots.txt" ]] && return 0
    [[ "$path_lower" =~ (^|/)security\.txt$ ]] && return 0
    [[ "$path_lower" =~ (^|/)(openapi|swagger|api-docs?)(\.|/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(graphql|graphiql|wsdl|wadl)(\.|/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)\.well-known(/|$) ]] && return 0
    [[ "$path_lower" =~ (^|/)(assetlinks\.json|apple-app-site-association|manifest\.json|crossdomain\.xml|clientaccesspolicy\.xml)$ ]] && return 0
    [[ "$path_lower" =~ (^|/)(config|settings|app-config|bootstrap|runtime)(\.|-|_|/|$) ]] && return 0

    # Exposed file-repository paths are valuable, but only the high-signal subset
    # should enter the serialized source-analysis queue. Otherwise generic docs and
    # link files starve API follow-up work and tank recall.
    if _source_queue_is_repo_artifact_path "$path_lower"; then
        _source_queue_is_high_signal_repo_artifact "$path_lower"
        return $?
    fi

    [[ "$path_lower" =~ \.(bak|backup|old|orig|save|swp|tmp|kdbx|sqlite|db|sql|dump|log|ya?ml|toml|ini|cfg|conf|env|pem|key|crt|cer|p12|pfx|ovpn|ppk|pyc|plist)(\.|$) ]] && return 0
    return 1
}

should_enqueue_case() {
    local source_name="$(_source_queue_lower "$1")"
    local case_type="$(_source_queue_lower "$2")"
    local _method="$3"
    local url="$4"
    local url_path="$5"
    local path_lower

    if [[ "$source_name" != "source-analyzer" ]]; then
        return 0
    fi

    path_lower="$(_source_queue_lower "$(_source_queue_path "$url_path" "$url")")"

    case "$case_type" in
        api|api-spec|graphql|form|upload|websocket|javascript|stylesheet)
            return 0
            ;;
        data)
            _source_queue_is_high_signal_data "$path_lower"
            return $?
            ;;
        page|unknown)
            _source_queue_is_high_signal_page "$path_lower"
            return $?
            ;;
        image|video|font|archive)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}
