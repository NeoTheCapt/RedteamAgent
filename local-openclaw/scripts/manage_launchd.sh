#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
LAUNCHD_DIR="$ROOT_DIR/launchd"

LABEL="${LOCAL_OPENCLAW_LAUNCHD_LABEL:-com.neothecapt.redteamopencode.scan-optimizer}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

ACTION="${1:-status}"

cmd_install() {
  local INTERVAL="${LOCAL_OPENCLAW_INTERVAL_SECONDS:-900}"
  local ENV_FILE="${LOCAL_OPENCLAW_ENV_FILE:-$STATE_DIR/scheduler.env}"
  local PLIST_PATH="$LAUNCHD_DIR/$LABEL.plist"
  local ENTRYPOINT="$ROOT_DIR/scripts/launchd_entrypoint.sh"
  local OUT_LOG="$ROOT_DIR/logs/launchd-stdout.log"
  local ERR_LOG="$ROOT_DIR/logs/launchd-stderr.log"

  mkdir -p "$STATE_DIR" "$LAUNCHD_DIR" "$LAUNCH_AGENTS_DIR" "$ROOT_DIR/logs"

  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$STATE_DIR/scheduler.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Created env template at $ENV_FILE; fill ORCH_TOKEN and PROJECT_ID before loading." >&2
  fi

  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>${ENTRYPOINT}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>LOCAL_OPENCLAW_ENV_FILE</key>
      <string>${ENV_FILE}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>${INTERVAL}</integer>
    <key>StandardOutPath</key>
    <string>${OUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${ERR_LOG}</string>
    <key>WorkingDirectory</key>
    <string>${ROOT_DIR}</string>
  </dict>
</plist>
EOF

  cp "$PLIST_PATH" "$TARGET_PLIST"

  if grep -q '^ORCH_TOKEN=$' "$ENV_FILE" || grep -q '^PROJECT_ID=$' "$ENV_FILE"; then
    echo "LaunchAgent plist written to $TARGET_PLIST but not loaded because ORCH_TOKEN/PROJECT_ID are missing in $ENV_FILE" >&2
    exit 0
  fi

  launchctl bootout "$GUI_DOMAIN" "$TARGET_PLIST" >/dev/null 2>&1 || true
  launchctl bootstrap "$GUI_DOMAIN" "$TARGET_PLIST"
  launchctl enable "$GUI_DOMAIN/$LABEL"
  launchctl kickstart -k "$GUI_DOMAIN/$LABEL"

  echo "Loaded $LABEL from $TARGET_PLIST"
  echo "Interval: ${INTERVAL}s"
  echo "Env file: $ENV_FILE"
}

cmd_uninstall() {
  launchctl bootout "$GUI_DOMAIN" "$TARGET_PLIST" >/dev/null 2>&1 || true
  rm -f "$TARGET_PLIST"
  echo "Unloaded and removed $TARGET_PLIST"
}

cmd_status() {
  if [[ -f "$TARGET_PLIST" ]]; then
    echo "plist: $TARGET_PLIST"
  else
    echo "plist not installed: $TARGET_PLIST"
  fi
  launchctl print "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
}

case "$ACTION" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *)
    echo "usage: $0 {install|uninstall|status}" >&2
    exit 1
    ;;
esac
