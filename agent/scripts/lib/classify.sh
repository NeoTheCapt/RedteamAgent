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
  if printf '%s' "$url_path" | grep -qiE '/ws(/|$)'; then
    echo "websocket"; return
  fi

  # 3. api
  if printf '%s' "$url_path" | grep -qiE '/api/|/v[0-9]/'; then
    echo "api"; return
  fi
  if (( is_write_method )) && printf '%s' "$ct_lower" | grep -qiE 'application/json'; then
    echo "api"; return
  fi

  # 4. upload
  if printf '%s' "$ct_lower" | grep -qiE 'multipart/form-data'; then
    echo "upload"; return
  fi

  # 5. form
  if [ "$method_upper" = "POST" ] || [ "$method_upper" = "PUT" ]; then
    if printf '%s' "$ct_lower" | grep -qiE 'application/x-www-form-urlencoded'; then
      echo "form"; return
    fi
  fi

  # 6. javascript
  if printf '%s' "$path_no_query" | grep -qiE '\.js$'; then
    echo "javascript"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'text/javascript|application/javascript'; then
    echo "javascript"; return
  fi

  # 7. stylesheet
  if printf '%s' "$path_no_query" | grep -qiE '\.css$'; then
    echo "stylesheet"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'text/css'; then
    echo "stylesheet"; return
  fi

  # 8. page
  if printf '%s' "$path_no_query" | grep -qiE '\.(html?|xhtml|php|aspx?|jsp)$'; then
    echo "page"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'text/html|application/xhtml|image/svg\+xml'; then
    echo "page"; return
  fi

  # 9. data
  if printf '%s' "$path_no_query" | grep -qiE '\.(json|xml|csv|ya?ml)$'; then
    echo "data"; return
  fi
  if printf '%s' "$ct_lower" | grep -qiE 'application/json|application/xml|text/csv|text/xml|application/pdf|text/plain|application/ld\+json|text/markdown'; then
    echo "data"; return
  fi

  # 10. image (excluding svg, already handled as page)
  if printf '%s' "$ct_lower" | grep -qiE '^image/' && ! printf '%s' "$ct_lower" | grep -qiE 'svg'; then
    echo "image"; return
  fi
  if printf '%s' "$path_no_query" | grep -qiE '\.(png|jpg|jpeg|gif|webp|ico|bmp|tiff|avif|apng)$'; then
    echo "image"; return
  fi

  # 11. video
  if printf '%s' "$ct_lower" | grep -qiE '^(video|audio)/'; then
    echo "video"; return
  fi
  if printf '%s' "$path_no_query" | grep -qiE '\.(mp4|webm|avi|mp3|wav|ogg)$'; then
    echo "video"; return
  fi

  # 12. font
  if printf '%s' "$ct_lower" | grep -qiE '^font/|application/vnd\.ms-fontobject'; then
    echo "font"; return
  fi
  if printf '%s' "$path_no_query" | grep -qiE '\.(woff|woff2|ttf|otf|eot)$'; then
    echo "font"; return
  fi

  # 13. archive
  if printf '%s' "$ct_lower" | grep -qiE 'zip|gzip|tar|rar|7z|bzip'; then
    echo "archive"; return
  fi

  # 14. unknown
  echo "unknown"
}
