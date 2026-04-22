#!/usr/bin/env python3
"""Deliver a cycle-report message through Hermes' send_message_tool.

Invoked by hermes_openclaw_compat.sh in response to the legacy
    openclaw message send --channel <platform> --target <ref> --message <body>
contract. This helper:
  1. Loads ~/.hermes/.env so gateway config sees platform tokens.
  2. Translates `user:<discord_user_id>` → the corresponding DM channel id
     via Discord's POST /users/@me/channels endpoint.
  3. Delegates to tools.send_message_tool.send_message_tool for the final
     platform call.

Exits 0 on success. Prints the JSON tool result on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_AGENT = HERMES_HOME / "hermes-agent"


def load_env() -> None:
    env_path = HERMES_HOME / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def resolve_discord_dm(user_id: str) -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN not set; cannot resolve DM channel")

    import urllib.request
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me/channels",
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-openclaw-compat (delivery, 1.0)",
        },
        data=json.dumps({"recipient_id": user_id}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
    channel_id = body.get("id")
    if not channel_id:
        raise SystemExit(f"Discord did not return a DM channel for user {user_id}: {body}")
    return str(channel_id)


def coerce_target(platform: str, target: str) -> str:
    """Translate legacy controller target syntax into send_message_tool format."""
    platform = platform.strip().lower()
    target = target.strip()

    if platform == "discord" and target.startswith("user:"):
        user_id = target.split(":", 1)[1].strip()
        dm_channel = resolve_discord_dm(user_id)
        return f"discord:{dm_channel}"

    # Already in "<platform>:<ref>" shape.
    if ":" in target and target.split(":", 1)[0].lower() == platform:
        return target

    return f"{platform}:{target}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="Platform id, e.g. discord / telegram")
    parser.add_argument("--target", required=True, help="Platform-specific target ref")
    parser.add_argument("--message", required=True, help="Message body")
    args = parser.parse_args()

    load_env()

    if not HERMES_AGENT.exists():
        print(f"[hermes_send_message] {HERMES_AGENT} not found; cannot deliver", file=sys.stderr)
        return 1
    sys.path.insert(0, str(HERMES_AGENT))

    try:
        resolved_target = coerce_target(args.channel, args.target)
    except SystemExit as exc:
        print(f"[hermes_send_message] target resolution failed: {exc}", file=sys.stderr)
        return 2

    try:
        from tools.send_message_tool import send_message_tool  # type: ignore
    except Exception as exc:
        print(f"[hermes_send_message] failed to import send_message_tool: {exc}", file=sys.stderr)
        return 3

    result = send_message_tool(
        {
            "action": "send",
            "target": resolved_target,
            "message": args.message,
        }
    )

    print(result)
    try:
        parsed = json.loads(result)
    except Exception:
        return 0
    if isinstance(parsed, dict) and parsed.get("error"):
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
