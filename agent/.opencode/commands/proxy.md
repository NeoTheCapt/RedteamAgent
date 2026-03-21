# Command: Proxy Control

You are the operator managing the mitmproxy interception proxy for the current engagement. The user's arguments specify the action: `start` or `stop`.

## Step 1: Locate Active Engagement

Find the most recent engagement directory under `engagements/`:

```bash
ENG_DIR=$(ls -td engagements/*/ 2>/dev/null | head -1 | sed 's|/$||')
echo "Engagement: $ENG_DIR"
```

If no engagement directory exists, inform the user to run `/engage` first and stop.

## Step 2: Parse Action

Read the user's arguments appended below this template. Expect one of:
- `start` — launch the proxy container
- `stop` — terminate the proxy container

If no action is provided, default to `start`.

## Action: Start

```bash
source scripts/lib/container.sh
export ENGAGEMENT_DIR="$ENG_DIR"
start_proxy
```

This starts the `redteam-proxy` Docker container with:
- Port 8080 exposed via `--network host`
- Engagement directory mounted at `/engagement`
- proxy_addon.py writing to cases.db and auth.json

Tell the user: "Proxy listening on port 8080. Configure browser proxy: http://127.0.0.1:8080"

## Action: Stop

```bash
source scripts/lib/container.sh
stop_proxy
```

This stops and removes the `redteam-proxy` Docker container.

## User Arguments

The action and any additional options from the user follows:
