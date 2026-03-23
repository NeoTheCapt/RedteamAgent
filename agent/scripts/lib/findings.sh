#!/usr/bin/env bash

finding_prefix_for_agent() {
    local agent_name="${1:?agent name required}"

    case "$agent_name" in
        exploit-developer) printf '%s\n' "EX" ;;
        vulnerability-analyst) printf '%s\n' "VA" ;;
        source-analyzer) printf '%s\n' "SA" ;;
        recon-specialist) printf '%s\n' "RE" ;;
        fuzzer) printf '%s\n' "FZ" ;;
        osint-analyst) printf '%s\n' "OS" ;;
        *)
            echo "unknown finding prefix for agent: $agent_name" >&2
            return 1
            ;;
    esac
}

finding_lock_path() {
    local eng_dir="${1:?engagement dir required}"
    printf '%s\n' "$eng_dir/.finding-id.lock"
}

acquire_finding_lock() {
    local eng_dir="${1:?engagement dir required}"
    local lock_dir
    lock_dir="$(finding_lock_path "$eng_dir")"
    local attempts=0

    while ! mkdir "$lock_dir" 2>/dev/null; do
        attempts=$((attempts + 1))
        if [[ "$attempts" -ge 200 ]]; then
            echo "failed to acquire finding lock: $lock_dir" >&2
            return 1
        fi
        sleep 0.05
    done

    printf '%s\n' "$lock_dir"
}

release_finding_lock() {
    local lock_dir="${1:?lock dir required}"
    rmdir "$lock_dir" 2>/dev/null || true
}

next_finding_id() {
    local eng_dir="${1:?engagement dir required}"
    local agent_name="${2:?agent name required}"
    local findings_file="$eng_dir/findings.md"
    local prefix max_id next_num

    prefix="$(finding_prefix_for_agent "$agent_name")"
    max_id="$(
        rg -o "FINDING-${prefix}-[0-9]{3}" "$findings_file" 2>/dev/null \
            | sed "s/FINDING-${prefix}-//" \
            | sort -n \
            | tail -1
    )"
    max_id="${max_id:-0}"
    next_num=$((10#$max_id + 1))
    printf 'FINDING-%s-%03d\n' "$prefix" "$next_num"
}

update_finding_count() {
    local findings_file="${1:?findings file required}"
    local count tmp_file

    count="$(rg -c '^## \[FINDING-[A-Z]{2}-[0-9]{3}\]' "$findings_file" 2>/dev/null || printf '0')"
    tmp_file="$(mktemp "${TMPDIR:-/tmp}/findings-count.XXXXXX")"

    awk -v count="$count" '
        BEGIN { updated = 0 }
        /^\- \*\*Finding Count\*\*:/ {
            print "- **Finding Count**: " count
            updated = 1
            next
        }
        { print }
        END {
            if (!updated) {
                print ""
                print "- **Finding Count**: " count
            }
        }
    ' "$findings_file" >"$tmp_file"

    mv "$tmp_file" "$findings_file"
}

replace_finding_placeholder() {
    local input_file="${1:?input file required}"
    local finding_id="${2:?finding id required}"
    local output_file="${3:?output file required}"

    awk -v finding_id="$finding_id" '
        BEGIN { replaced = 0 }
        {
            line = $0
            if (!replaced && line ~ /^## \[(FINDING-ID|FINDING-[A-Z]{2}-[0-9]{3})\]/) {
                sub(/\[(FINDING-ID|FINDING-[A-Z]{2}-[0-9]{3})\]/, "[" finding_id "]", line)
                replaced = 1
            }
            print line
        }
        END {
            if (!replaced) {
                exit 42
            }
        }
    ' "$input_file" >"$output_file"
}
