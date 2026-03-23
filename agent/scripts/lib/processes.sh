#!/bin/bash
# scripts/lib/processes.sh — lightweight local process management helpers

pid_file_path() {
    local pid_dir="$1"
    local name="$2"
    mkdir -p "$pid_dir"
    echo "$pid_dir/$name.pid"
}

pid_is_running() {
    local pid_file="$1"
    [ -f "$pid_file" ] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

start_managed_process() {
    local pid_dir="$1"
    local name="$2"
    shift 2

    local pid_file
    pid_file=$(pid_file_path "$pid_dir" "$name")

    if pid_is_running "$pid_file"; then
        echo "[$name] Already running"
        return 0
    fi

    rm -f "$pid_file"
    "$@" >/dev/null 2>&1 &
    local pid=$!
    printf '%s\n' "$pid" > "$pid_file"
    echo "[$name] Started"
}

stop_managed_process() {
    local pid_dir="$1"
    local name="$2"
    local pid_file
    pid_file=$(pid_file_path "$pid_dir" "$name")

    if ! [ -f "$pid_file" ]; then
        echo "[$name] Not running"
        return 0
    fi

    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi

    rm -f "$pid_file"
    echo "[$name] Stopped"
}
