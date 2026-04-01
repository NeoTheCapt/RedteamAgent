#!/bin/bash
# Parameter extraction and dedup signature helpers for the case collection pipeline.
# This file is intended to be sourced, not executed directly.

# Ensure common tool directories are in PATH (needed when sourced from zsh)
for _params_dir in /usr/bin /usr/local/bin /opt/homebrew/bin /sbin; do
  case ":$PATH:" in
    *":$_params_dir:"*) ;;
    *) [ -d "$_params_dir" ] && PATH="$_params_dir:$PATH" ;;
  esac
done
unset _params_dir

# extract_query_params <url>
# Parse URL query string into a JSON object {"key":"value",...}.
# Returns {} if no query string is present.
extract_query_params() {
  local url="$1"
  local qs

  # Strip fragment first, then extract query string
  url="${url%%#*}"
  case "$url" in
    *\?*) qs="${url#*\?}" ;;
    *)    echo "{}"; return 0 ;;
  esac

  if [ -z "$qs" ]; then
    echo "{}"
    return 0
  fi

  # Split on & and build JSON via jq
  echo "$qs" | tr '&' '\n' | awk -F'=' '{
    key = $1
    val = ""
    if (NF > 1) {
      # Rejoin in case value contains '='
      for (i = 2; i <= NF; i++) {
        if (i > 2) val = val "="
        val = val $i
      }
    }
    printf "%s\t%s\n", key, val
  }' | jq -Rn '
    [inputs | split("\t") | {(.[0]): (.[1] // "")}] | add // {}
  '
}

# extract_url_path <url>
# Extract the path portion of a URL, stripping scheme, host, query, and fragment.
extract_url_path() {
  local url="$1"

  # Strip fragment
  url="${url%%#*}"
  # Strip query string
  url="${url%%\?*}"

  # Strip scheme + authority (e.g., https://host:port)
  case "$url" in
    *://*)
      url="${url#*://}"    # remove scheme://
      case "$url" in
        */*)
          url="/${url#*/}"   # remove host part, keep leading /
          ;;
        *)
          url="/"            # host-only URL maps to the root path
          ;;
      esac
      ;;
  esac

  # Ensure leading slash
  case "$url" in
    /*) ;;
    *)  url="/$url" ;;
  esac

  echo "$url"
}

# extract_url_origin <url>
# Extract lowercased scheme://host[:port] from a URL for cross-origin dedup.
# Returns empty string for relative URLs.
extract_url_origin() {
  local url="$1"

  case "$url" in
    *://*) ;;
    *) echo ""; return 0 ;;
  esac

  python3 - "$url" <<'PY'
import sys
from urllib.parse import urlsplit
u = urlsplit(sys.argv[1])
scheme = (u.scheme or '').lower()
netloc = (u.netloc or '').lower()
print(f"{scheme}://{netloc}" if scheme and netloc else "")
PY
}

# extract_path_params <path>
# Identify dynamic URL segments using heuristics.
# Returns JSON like {"seg_N":"value"} for each detected dynamic segment.
extract_path_params() {
  local url_path="$1"
  local idx=0
  local result="{}"

  # Remove leading slash, split on /
  local stripped="${url_path#/}"
  if [ -z "$stripped" ]; then
    echo "{}"
    return 0
  fi

  # Use jq to split path and identify dynamic segments in one pass
  # This avoids shell-level splitting issues between bash and zsh
  local _jq_filter='input | split("/") | to_entries | reduce .[] as $e ({};($e.value) as $seg | ($e.key + 1) as $idx | if ($seg | test("^[0-9]+$")) then . + {("seg_\($idx)"): $seg} elif ($seg | test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) then . + {("seg_\($idx)"): $seg} elif ($seg | test("^[0-9a-fA-F]{24,}$")) then . + {("seg_\($idx)"): $seg} else . end)'
  result=$(printf '%s' "$stripped" | jq -Rn "$_jq_filter")

  echo "$result"
}

# extract_cookie_params <cookie_header_value>
# Parse a Cookie header string into a JSON object.
extract_cookie_params() {
  local cookie_str="$1"

  if [ -z "$cookie_str" ]; then
    echo "{}"
    return 0
  fi

  # Split on "; " or ";" and parse key=value pairs
  echo "$cookie_str" | tr ';' '\n' | sed 's/^ *//' | awk -F'=' '{
    key = $1
    val = ""
    if (NF > 1) {
      for (i = 2; i <= NF; i++) {
        if (i > 2) val = val "="
        val = val $i
      }
    }
    # Skip empty keys
    if (key != "") printf "%s\t%s\n", key, val
  }' | jq -Rn '
    [inputs | split("\t") | {(.[0]): (.[1] // "")}] | add // {}
  '
}

# generate_params_sig <query_params_json> <body_params_json> [url]
# Generate a dedup signature: md5 hash of lowercased origin + sorted parameter KEY names.
# Requests on different origins/ports must not collapse into the same queue entry.
generate_params_sig() {
  local query_json="${1:-"{}"}"
  local body_json="${2:-"{}"}"
  local url="${3:-}"
  local origin
  origin="$(extract_url_origin "$url")"

  # Merge keys from both JSON objects, sort, and join with the request origin.
  local dedup_material
  dedup_material=$(printf '%s\n%s\n%s' "$query_json" "$body_json" "$origin" | jq -Rs '
    split("\n") as $parts
    | ($parts[0] | fromjson? // {}) as $q
    | ($parts[1] | fromjson? // {}) as $b
    | ($parts[2] // "") as $origin
    | [$origin, ((($q | keys) + ($b | keys)) | unique | join(","))] | join("|")
  ')

  # Hash with md5 (macOS) or md5sum (Linux)
  local hash
  if command -v md5 >/dev/null 2>&1; then
    hash=$(printf '%s' "$dedup_material" | md5)
  elif command -v md5sum >/dev/null 2>&1; then
    hash=$(printf '%s' "$dedup_material" | md5sum | awk '{print $1}')
  else
    echo "ERROR: no md5 tool found" >&2
    return 1
  fi

  echo "$hash"
}
