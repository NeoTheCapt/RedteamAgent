# Command: OSINT Intelligence Gathering

You are the operator initiating OSINT intelligence gathering on the current engagement.

## Steps

1. Find the active engagement directory:
   ```bash
   ENG_DIR=$(ls -td engagements/*/ 2>/dev/null | head -1 | sed 's|/$||')
   ```

2. Verify intel.md exists in the engagement directory. If not, create it with the empty template.

3. Dispatch @osint-analyst with:
   - Engagement path: $ENG_DIR
   - intel.md content summary
   - Target domain/org from scope.json
   - Objective: "Full OSINT sweep — CVE lookup, breach search, DNS history, social profiling"

4. After osint-analyst completes:
   - Append results to intel.md (appropriate sections)
   - Read Intelligence Assessment
   - HIGH-value items → write to findings.md + dispatch exploit-developer
   - Historical endpoints → requeue to cases.db
