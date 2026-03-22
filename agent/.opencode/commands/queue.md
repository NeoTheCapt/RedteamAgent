# Command: Queue Status

You are the operator checking the case queue status for the current engagement.

## Step 1: Locate Active Engagement

Find the most recent engagement directory under `engagements/`:

```bash
source scripts/lib/engagement.sh
resolve_engagement_dir "$(pwd)"
```

If no engagement directory exists, inform the user to run `/engage` first and stop.

## Step 2: Check Database Exists

Verify that `cases.db` exists in the engagement directory:

```bash
test -f "<engagement_dir>/cases.db" && echo "exists" || echo "missing"
```

If cases.db does not exist, inform the user that the case database has not been initialized. Suggest running `/engage` to initialize the engagement or checking that ingest scripts have been run.

## Step 3: Display Queue Stats

Run the dispatcher stats command:

```bash
./scripts/dispatcher.sh "<engagement_dir>/cases.db" stats
```

## Step 4: Present Results

Display the stats output in a clear, readable format. Highlight:
- Total number of cases
- Breakdown by status (`pending`, `processing`, `done`, `error`)
- Breakdown by type if available
- Any stale cases that may need attention

## User Arguments

Additional context or filter options from the user follows:
