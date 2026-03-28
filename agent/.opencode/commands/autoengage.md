# Command: Full Autonomous Engagement

This is a shortcut for `/engage --auto`. Run the engage workflow in fully autonomous mode.

**RULES:**
1. NEVER ask the user anything. No numbered choices. No approval requests.
2. NEVER stop and wait. If something fails, log it and move on.
3. Auto-select PARALLEL for everything.
4. Only stop when all cases are processed, processing=0, attack paths are exhausted, collection health passes, and surface coverage is resolved, OR user types `/stop`.
5. If stopping for any non-completion reason, emit an explicit stop reason in the format:
   `Stop reason: <code> — <reason>`

## Execute

Follow the exact same steps as `/engage`, but with `--auto` flag:

--auto $ARGUMENTS
