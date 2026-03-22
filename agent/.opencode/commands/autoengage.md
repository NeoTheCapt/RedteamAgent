# Command: Full Autonomous Engagement

This is a shortcut for `/engage --auto`. Run the engage workflow in fully autonomous mode.

**RULES:**
1. NEVER ask the user anything. No numbered choices. No approval requests.
2. NEVER stop and wait. If something fails, log it and move on.
3. Auto-select PARALLEL for everything.
4. Only stop when all cases processed + all attack paths exhausted, OR user types `/stop`.

## Execute

Follow the exact same steps as `/engage`, but with `--auto` flag:

--auto $ARGUMENTS
