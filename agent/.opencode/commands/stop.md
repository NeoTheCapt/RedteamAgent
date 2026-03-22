# Command: Stop Engagement Processes

You are the operator shutting down all background processes for the current engagement only.

## Step 1: Locate Active Engagement

```bash
source scripts/lib/engagement.sh
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
echo "Engagement: $ENG_DIR"
```

If no engagement directory exists, inform the user that no active engagement was found.

## Step 2: Stop All Containers

```bash
source scripts/lib/container.sh
stop_all_containers
```

This stops the mitmproxy and Katana Docker containers for the active engagement if running.
It must not stop containers belonging to another engagement.

## Step 3: Show Final Queue Stats

If `cases.db` exists, display final queue statistics:

```bash
./scripts/dispatcher.sh "$ENG_DIR/cases.db" stats
```

## Step 4: Suggest Next Steps

Ask the user if they would like to:
- Generate a final report now with `/report`
- Review findings in `<engagement_dir>/findings.md`
- Resume processing later (containers can be restarted)

## User Arguments

Additional context from the user follows:
