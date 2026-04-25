#!/bin/bash
# scripts/lib/processes.sh — lightweight local process management helpers

pid_file_path() {
    local pid_dir="$1"
    local name="$2"
    mkdir -p "$pid_dir"
    echo "$pid_dir/$name.pid"
}

pid_command_file_path() {
    local pid_file="$1"
    echo "${pid_file}.cmd"
}

clear_pid_tracking() {
    local pid_file="$1"
    rm -f "$pid_file" "$(pid_command_file_path "$pid_file")"
}

write_pid_tracking() {
    local pid_file="$1"
    local pid="$2"
    local expected_command="${3:-}"

    printf '%s\n' "$pid" > "$pid_file"
    if [ -n "$expected_command" ]; then
        printf '%s\n' "$expected_command" > "$(pid_command_file_path "$pid_file")"
    else
        rm -f "$(pid_command_file_path "$pid_file")"
    fi
}

pid_is_running() {
    local pid_file="$1"
    local expected_command="${2:-}"
    [ -f "$pid_file" ] || return 1

    local pid stat command command_file
    pid=$(cat "$pid_file" 2>/dev/null || true)
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1

    stat=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)
    [ -n "$stat" ] || return 1
    [[ "$stat" != Z* ]] || return 1

    command=$(ps -o command= -p "$pid" 2>/dev/null || true)
    [ -n "$command" ] || return 1

    if [ -z "$expected_command" ]; then
        command_file="$(pid_command_file_path "$pid_file")"
        if [ -f "$command_file" ]; then
            expected_command=$(cat "$command_file" 2>/dev/null || true)
        fi
    fi

    if [ -n "$expected_command" ] && [[ "$command" != *"$expected_command"* ]]; then
        return 1
    fi

    return 0
}

start_managed_process() {
    local pid_dir="$1"
    local name="$2"
    local expected_command="${3:-}"
    shift 3

    local pid_file
    pid_file=$(pid_file_path "$pid_dir" "$name")

    if pid_is_running "$pid_file" "$expected_command"; then
        echo "[$name] Already running"
        return 0
    fi

    clear_pid_tracking "$pid_file"
    nohup "$@" >/dev/null 2>&1 < /dev/null &
    local pid=$!
    write_pid_tracking "$pid_file" "$pid" "$expected_command"
    echo "[$name] Started"
}

stop_managed_process() {
    local pid_dir="$1"
    local name="$2"
    local expected_command="${3:-}"
    local pid_file
    pid_file=$(pid_file_path "$pid_dir" "$name")

    if ! [ -f "$pid_file" ]; then
        echo "[$name] Not running"
        return 0
    fi

    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [ -n "$pid" ] && pid_is_running "$pid_file" "$expected_command"; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi

    clear_pid_tracking "$pid_file"
    echo "[$name] Stopped"
}
