# Command: Toggle Confirmation Mode

You are the operator switching between auto-confirm and manual-confirm modes.

## Parse Arguments

The user's arguments appended below specify the mode:
- `auto` — auto-confirm mode (default): parallel dispatch and phase transitions happen automatically
- `manual` — manual-confirm mode: every decision requires numbered user approval

If no argument provided, show current mode status.

## Action: auto

1. Update scope.json — set `confirm_mode` to `"auto"`:
   ```bash
   ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
   if [ -n "$ENG_DIR" ] && [ -f "$ENG_DIR/scope.json" ]; then
       jq '.confirm_mode = "auto"' "$ENG_DIR/scope.json" > "$ENG_DIR/scope_tmp.json" && mv "$ENG_DIR/scope_tmp.json" "$ENG_DIR/scope.json"
   fi
   ```

2. Announce:
   ```
   [operator] Auto-confirm mode ON.
     - Parallel dispatch: automatic (no prompt)
     - Phase transitions: automatic (brief announcement only)
     - Will only stop for: auth setup, unexpected situations
   ```

## Action: manual

1. Update scope.json — set `confirm_mode` to `"manual"`:
   ```bash
   ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
   if [ -n "$ENG_DIR" ] && [ -f "$ENG_DIR/scope.json" ]; then
       jq '.confirm_mode = "manual"' "$ENG_DIR/scope.json" > "$ENG_DIR/scope_tmp.json" && mv "$ENG_DIR/scope_tmp.json" "$ENG_DIR/scope.json"
   fi
   ```

2. Announce:
   ```
   [operator] Manual-confirm mode ON.
     - Parallel dispatch: requires approval (1-2)
     - Phase transitions: requires approval (1-2)
     - Every action will wait for user confirmation
   ```

## Action: (no argument / status)

Read current mode from scope.json:
```bash
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
MODE=$(jq -r '.confirm_mode // "auto"' "$ENG_DIR/scope.json" 2>/dev/null || echo "auto")
echo "Current mode: $MODE"
```

Show:
```
[operator] Current mode: <auto|manual>
  /confirm auto   — switch to auto-confirm
  /confirm manual — switch to manual-confirm
```

## User Arguments

The mode argument from the user follows:
