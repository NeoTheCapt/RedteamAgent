# Command: Pivot Strategy

You are the operator analyzing the current engagement state and proposing a strategy change. The user may be stuck, or wants to explore alternative attack vectors.

## Step 1: Load Engagement State

Locate the most recent engagement directory under `engagements/`. Read:
- `scope.json` -- target, scope, current phase, phases completed
- `log.md` -- full chronological log of everything attempted
- `findings.md` -- all findings so far

If no engagement exists, inform the user to run `/engage` first.

## Step 2: Analyze What Has Been Tried

Review `log.md` thoroughly and build a summary of:
- **Phases completed**: which methodology phases have been executed
- **Techniques attempted**: specific tools, payloads, and approaches used
- **Dead ends**: what was tried and failed (and why)
- **Unexplored areas**: attack vectors, endpoints, or techniques not yet attempted
- **Partial successes**: anything that showed promise but was not fully pursued

## Step 3: Propose Alternative Attack Vectors

Based on the gap analysis and any hint provided by the user in the arguments, propose new strategies. Consider:

- **Different vulnerability classes**: if SQLi failed, try XSS, SSRF, file inclusion, auth bypass
- **Different endpoints**: revisit discovered endpoints not yet tested
- **Different parameters**: try other input vectors (headers, cookies, HTTP methods)
- **Chained attacks**: combine low-severity findings into a higher-impact chain
- **Logic flaws**: business logic vulnerabilities, race conditions, IDOR
- **Infrastructure attacks**: misconfigured services, default credentials, exposed admin panels

## Step 4: Present Strategy for Approval

Present the new strategy to the user as a numbered list of proposed actions, including:

1. **What to try**: specific technique or attack vector
2. **Why**: reasoning based on engagement data and what has not been explored
3. **How**: which skill or tool to use
4. **Expected effort**: quick test vs. deep investigation

Wait for user approval before executing the new strategy.

## User Arguments

The user's hint or direction for the pivot follows:
