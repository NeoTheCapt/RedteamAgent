#!/bin/bash
# Type classification library for the case collection pipeline.
# Sourced by producers to classify HTTP requests into case types.

classify_type() {
  local method="$1"
  local url_path="$2"
  local content_type="$3"
  local body_snippet="$4"

  local method_upper
  method_upper="$(printf '%s' "$method" | tr '[:lower:]' '[:upper:]')"
  local ct_lower
  ct_lower="$(printf '%s' "$content_type" | tr '[:upper:]' '[:lower:]')"

  # Strip query string from url_path for extension checks
  local path_no_query="${url_path%%\?*}"
  local is_write_method=0
  if [[ "$method_upper" =~ ^(POST|PUT|PATCH|DELETE)$ ]]; then
    is_write_method=1
  fi

  # 1. graphql
  if printf '%s' "$url_path" | grep -qiE '/graphql'; then
    echo "graphql"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE '^application/graphql$'; then
    echo "graphql"; return
  fi
  if [ -n "$body_snippet" ]; then
    local qval
    qval="$(printf '%s' "$body_snippet" | jq -r '.query // empty' 2>/dev/null)"
    if [ -n "$qval" ]; then
      if printf '%s' "$qval" | grep -qE '\{.*\}'; then
        echo "graphql"; return
      fi
    fi
  fi

  # 2. websocket
  if printf '%s' "$url_path" | grep -qiE '^wss?://'; then
    echo "websocket"; return
  fi
  if printf '%s' "$url_path" | grep -qiE '/ws(/|$)|^/socket\.io(/|$)'; then
    echo "websocket"; return
  fi

  # 3. api spec / documentation
  if printf '%s' "$url_path" | grep -qiE '^/(api-docs|openapi(\.json)?|swagger(\.json|-ui(\.html)?)?|v[0-9]+/api-docs)(/|$)'; then
    echo "api-spec"; return
  fi

  # 4. api
  if printf '%s' "$url_path" | grep -qiE '^/(api|rest)(/|$)|/v[0-9]+(/|$)'; then
    echo "api"; return
  fi
  if (( is_write_method )) && printf '%s' "$ct_lower" | grep -qiE 'application/json'; then
    echo "api"; return
  fi

  # 5. upload
  if printf '%s' "$ct_lower" | grep -qiE 'multipart/form-data'; then
    echo "upload"; return
  fi

  # 6. form
  if [ "$method_upper" = "POST" ] || [ "$method_upper" = "PUT" ]; then
    if printf '%s' "$ct_lower" | grep -qiE 'application/x-www-form-urlencoded'; then
      echo "form"; return
    fi
  fi

  # 7. response content-type overrides extension-based asset guesses.
  # This avoids misclassifying SPA fallback HTML (200 text/html) as javascript/stylesheet
  # solely because the requested path ends with .js/.css.
  if printf '%s' "$ct_lower" | grep -qiE 'text/html|application/xhtml|image/svg\+xml'; then
    echo "page"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'application/json|application/xml|text/csv|text/xml|application/pdf|text/plain|application/ld\+json|text/markdown'; then
    echo "data"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE '^image/' && ! printf '%s' "$ct_lower" | grep -qiE 'svg'; then
    echo "image"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE '^(video|audio)/'; then
    echo "video"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE '^font/|application/vnd\.ms-fontobject'; then
    echo "font"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'zip|gzip|tar|rar|7z|bzip'; then
    echo "archive"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'text/javascript|application/javascript'; then
    echo "javascript"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'text/css'; then
    echo "stylesheet"; return
  fi

  # 8. javascript
  if printf '%s' "$path_no_query" | grep -qiE '\.js$'; then
    echo "javascript"; return
  fi

  # 9. stylesheet
  if printf '%s' "$path_no_query" | grep -qiE '\.css$'; then
    echo "stylesheet"; return
  fi

  # 10. page
  if printf '%s' "$path_no_query" | grep -qiE '\.(html?|xhtml|php|aspx?|jsp)$'; then
    echo "page"; return
  fi

  # 11. data
  if printf '%s' "$path_no_query" | grep -qiE '\.(json|xml|csv|ya?ml|txt)$'; then
    echo "data"; return
  fi

  # 12. image (excluding svg, already handled as page)
  if printf '%s' "$path_no_query" | grep -qiE '\.(png|jpg|jpeg|gif|webp|ico|bmp|tiff|avif|apng)$'; then
    echo "image"; return
  fi

  # 13. video
  if printf '%s' "$path_no_query" | grep -qiE '\.(mp4|webm|avi|mp3|wav|ogg)$'; then
    echo "video"; return
  fi

  # 14. font
  if printf '%s' "$path_no_query" | grep -qiE '\.(woff|woff2|ttf|otf|eot)$'; then
    echo "font"; return
  fi

  # 15. unknown
  echo "unknown"
}
