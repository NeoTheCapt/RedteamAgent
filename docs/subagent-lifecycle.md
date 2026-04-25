# Sub-Agent Lifecycle Decisions

How to decide whether a sub-agent should be created, kept, merged, or retired.
Reference this before changing anything under `.opencode/prompts/agents/` or
`opencode.json` `agent` block.

---

## When to read this

- A subagent is being proposed (new role)
- A subagent has 0 dispatches for ≥3 consecutive observed cycles ("ghost")
- A subagent's prompt is approaching the 25KB soft cap and someone wants to add more
- Two subagents look like they overlap (skills, tooling, or reasoning mode)

---

## The merge-vs-keep framework (three questions)

Apply these EVERY time someone proposes merging two subagents OR retiring one
into another. All three questions are pass/fail; the merge is justified only
when all three answer "same/yes".

### Q1 — Is the tool stack the same?

Look at the actual binaries / scripts / libraries each subagent invokes.
Different tools = different failure modes, different output parsing,
different retry semantics — keeping them apart limits blast radius.

### Q2 — Is the reasoning mode the same?

- "Per-case targeted analysis with 1-2 deep probes" (vulnerability-analyst)
- "High-volume statistical noise reduction across 1000+ responses" (fuzzer)
- "Cross-source correlation across many independent intel feeds" (osint-analyst)
- "Sequential exploit chain construction with state tracking" (exploit-developer)

These are genuinely different cognitive shapes. Forcing one subagent to
mode-switch within a single session burns context budget on context-switching
itself, not on the work. Keeping modes separate keeps each subagent's prompt
focused.

### Q3 — Does either side need a long-running session that would block the other?

If subagent A's typical task takes 5+ minutes (deep ffuf, full breach-DB query,
metasploit module run) and subagent B's task is per-case sub-minute work,
collapsing them means B's case batch processing gets stuck waiting for A's
long task to finish. Separate subagents = separate sessions = no head-of-line
blocking.

### Verdict matrix

| Q1 same? | Q2 same? | Q3 OK? | Action |
|---|---|---|---|
| ✓ | ✓ | ✓ | merge is justified |
| ✗ | any | any | don't merge — different tools means different failure handling |
| any | ✗ | any | don't merge — mode-switching within one session is expensive |
| any | any | ✗ | don't merge — long tasks block short ones |

If 2 of 3 lean against, **don't merge** — the merge will accumulate cost over
time even if it looks tidy short-term.

---

## Ghost subagent triage

A "ghost subagent" is one with 0 dispatches across ≥3 consecutive observed
cycles despite being registered in `opencode.json`. They look harmless but
carry persistent maintenance cost (prompt sync, AUTHORIZATION block updates,
finding-prefix bookkeeping, render script entries).

**Rule: ghost subagents must be processed within one audit cycle of detection.
Don't leave them in a "maybe useful someday" middle state.**

Three valid outcomes for a ghost:

1. **Activate via mechanical trigger** — the most common correct fix. The
   subagent's job is real; only the dispatch signal was unreliable. See
   "Trigger patterns" below.

2. **Retire and absorb** — only if all three merge-framework questions pass
   AND the absorbed responsibility doesn't push the receiver past 25KB
   prompt size or its primary reasoning mode out of focus.

3. **Delete outright** — only if the function is genuinely no longer needed
   (e.g., the underlying capability was removed from the toolchain).

Never leave a ghost subagent "for future use." If the trigger is unclear
today, it'll be unclear forever.

---

## Trigger patterns

Two patterns cover all observed cases. Use them; don't invent new prose
contracts that depend on an upstream agent remembering to emit a marker.

### Pattern A: per-case stage transition

Use when the subagent's work attaches to a SPECIFIC case in `cases.db`.

How: add a new value to the `stage` column. Some upstream subagent's
`### Case Outcomes` `DONE STAGE=<stage>` line transitions a case to that
stage. Operator's stage-based dispatch table picks it up.

Example: **fuzzer** (commit `93a3f54`).
- `vulnerability-analyst` triages a case, decides it needs >500-entry fuzz
- emits `DONE STAGE=fuzz_pending <id>` instead of advancing to `vuln_confirmed`
- operator dispatches `fuzzer` on `stage=fuzz_pending`
- `fuzzer` transitions case to `vuln_confirmed` / `api_tested` / `clean`

When to use:
- subagent acts on individual cases, not engagement-wide state
- caller already produces `### Case Outcomes` (the structured contract is
  free)
- the dispatch is one-shot per case

### Pattern B: flag-file watcher script

Use when the subagent's work is engagement-wide and triggered by accumulated
state, not a single case.

How: write a small `<thing>_changed_check.sh` that:
- reads the watched artifact (auth.json, intel.md, …)
- compares against a `.<thing>-respawn-state.json` high-water mark
- if state grew, writes a `.<thing>-respawn-required` flag with details
- preserves the high-water mark across compactions (never lower it)
- is idempotent (same content → no flag, even called repeatedly)

Operator skill calls the check every tick. If the flag exists, dispatches
the subagent and removes the flag.

Examples:
- **auth_respawn_check.sh** → re-dispatches `recon-specialist` + `source-analyzer`
  when `auth.json.validated_credentials` grew
- **intel_changed_check.sh** → dispatches `osint-analyst` when `intel.md`
  filled-row count grew (commit `b5fe956`)

When to use:
- subagent does global / cross-source correlation, not single-case work
- the dispatch isn't case-bound (osint queries intel.md as a whole; auth
  re-recon respawns under new identity, not "for case X")
- triggering is rate-limited (no need to fire per case)

---

## Anti-patterns to avoid

These were tried and rejected. Don't reintroduce them.

### Anti-pattern: prose-only dispatch contract

`vulnerability-analyst.txt` previously had: "When deeper fuzzing required,
emit a `FUZZER_NEEDED` block." Across many engagements `FUZZER_NEEDED`
appeared 0 times. Prose contracts that depend on an agent remembering to
write a marker FAIL — agents don't reliably emit out-of-band markers.

If you need a trigger, it has to be a STRUCTURED part of the agent's
existing required output (Case Outcomes stage transition) OR a state-watcher
script that doesn't depend on the agent at all (flag-file pattern).

### Anti-pattern: merging a ghost into a busy receiver "to clean up"

Merging fuzzer into vulnerability-analyst was tried (commit `e7ecbb5`,
later reverted at `32fb11e`). It looked tidy — fewer subagents, less
maintenance. But it failed Q2 (vulnerability-analyst's per-case probe mode
vs fuzzer's high-volume statistical mode are different cognitive shapes)
and Q3 (long ffuf runs would block v-analyst's case batches).

**Lesson**: the ghost wasn't a sign the subagent was unnecessary; it was a
sign the trigger was broken. Fix the trigger. Don't fold the role into a
subagent that wasn't designed for it.

### Anti-pattern: "we'll figure out the trigger later" with the subagent registered

A subagent registered in `opencode.json` but with no working trigger
contributes context overhead (prompt loaded for opencode session
introspection) and maintenance overhead (AUTHORIZATION block sync, finding
prefix mapping, etc.) without producing any value. If you can't write the
trigger now (Pattern A or B), don't register the subagent yet.

---

## Bloat prevention

Hard rules to keep subagent prompts maintainable:

- **25KB soft cap per subagent prompt.** Hitting it means the next addition
  goes into a helper script + 1-line hook in the prompt, not a new
  paragraph.
- **No new responsibility into existing subagent without checking the three
  merge questions in reverse.** If you'd reject the merge for those reasons,
  reject the load too.
- **Common blocks that appear verbatim in 4+ subagents** (e.g., SUBAGENT
  BOUNDARY) should have a CI consistency check rather than be edited
  in-place repeatedly.
- **Skills lists** in subagent prompts must reference real `agent/skills/`
  directory names. Drift between prompt-listed skills and actual skill
  directories triggers an audit.

---

## Reference cases

| Subagent | Status | Trigger | Why kept/changed |
|---|---|---|---|
| operator | primary | always | entry point |
| recon-specialist | active | initial discovery + auth-respawn flag | broad surface mapping |
| source-analyzer | active (overdispatched, separate concern) | stage=ingested + type∈{js,page,…} | static-analysis mode unique |
| vulnerability-analyst | active | stage=ingested + type∈{api,form,…} | main triage workhorse |
| exploit-developer | active | stage=vuln_confirmed | chain-attack + exploit construction |
| fuzzer | activated via Pattern A | stage=fuzz_pending | high-volume statistical mode unique |
| osint-analyst | activated via Pattern B | intel.md filled-row delta | cross-source correlation unique |
| report-writer | active | end-of-cycle | reporting concern unique |

If the next ghost shows up, walk the framework, pick a pattern, write the
trigger. Don't merge.
