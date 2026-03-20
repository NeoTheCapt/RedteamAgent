# Command: Engagement Status

You are the operator providing a status summary of the current engagement.

## Step 1: Load Engagement State

Locate the most recent engagement directory under `engagements/`. Read:
- `scope.json` -- target, scope, mode, status, phases completed, current phase
- `log.md` -- full engagement log
- `findings.md` -- all findings

If no engagement exists, inform the user that no active engagement was found.

## Step 2: Compile Status Dashboard

Analyze the engagement files and produce a concise status dashboard:

```
============================================
 ENGAGEMENT STATUS
============================================
 Target:          <target URL>
 Mode:            <mode>
 Status:          <in_progress | completed>
 Started:         <start time>
 Current Phase:   <phase name>
--------------------------------------------
 PHASE PROGRESS
--------------------------------------------
 [x] Recon          <completed | skipped>
 [x] Scan           <completed | skipped>
 [ ] Enumerate      <in progress | pending>
 [ ] Analyze        <pending>
 [ ] Exploit        <pending>
 [ ] Report         <pending>
--------------------------------------------
 FINDINGS SUMMARY
--------------------------------------------
 HIGH:    <count>
 MEDIUM:  <count>
 LOW:     <count>
 INFO:    <count>
 Total:   <count>
--------------------------------------------
 ATTACK PATHS EXPLORED
--------------------------------------------
 <list of techniques/vectors attempted>
--------------------------------------------
 NEXT STEPS
--------------------------------------------
 <recommended next actions>
============================================
```

## Step 3: Highlight Key Items

After the dashboard, briefly note:
- Any high-severity findings that need immediate attention
- Promising attack vectors not yet fully explored
- Blockers or issues encountered

## User Arguments

Additional context or specific status queries from the user follows:
