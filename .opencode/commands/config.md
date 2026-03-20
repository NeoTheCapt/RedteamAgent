# Command: Runtime Configuration

You are the operator managing runtime parameters for the current engagement.

## Step 1: Locate Active Engagement

```bash
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
echo "Engagement: $ENG_DIR"
```

If no engagement exists, inform user to run `/engage` first.

## Step 2: Parse Arguments

The user's arguments specify the action:
- `show` — display current configuration
- `<key> <value>` — set a configuration parameter
- No arguments — same as `show`

## Action: show

Read and display current config from scope.json:

```bash
echo "=== Current Configuration ==="
jq '{
  max_parallel_engagements: (.max_parallel_engagements // 3),
  batch_size: (.batch_size // 10),
  confirm_mode: (.confirm_mode // "auto")
}' "$ENG_DIR/scope.json"
echo ""
echo "Note: confirm_mode is managed by /confirm command, not /config"
```

## Action: set parameter

Supported parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `parallel` | 3 | Max concurrent sub-engagements for wildcard domains |
| `batch_size` | 10 | Cases per dispatcher fetch batch |

Update scope.json:

```bash
# Example: /config parallel 5
jq '.<parameter_name> = <value>' "$ENG_DIR/scope.json" > "$ENG_DIR/scope_tmp.json" \
  && mv "$ENG_DIR/scope_tmp.json" "$ENG_DIR/scope.json"
```

Map user-friendly names to scope.json fields:
- `parallel` → `.max_parallel_engagements`
- `batch_size` → `.batch_size`

Announce the change:
```
[operator] Config updated: <parameter> = <value>
```

## User Arguments

The parameter and value from the user follows:
