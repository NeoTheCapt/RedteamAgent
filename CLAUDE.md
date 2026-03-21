# Development Rules for RedTeam Agent

## Mandatory Review After Agent/Skill Changes

After ANY modification to files in `.opencode/prompts/agents/` or `skills/*/SKILL.md`:

1. **Agent division of labor** — verify each agent's role is clear and non-overlapping
2. **Handoff protocols** — verify every agent's output can be consumed by the next agent. Check operator.txt `ALL AGENT HANDOFF PROTOCOLS` section matches reality.
3. **Skill coverage** — every skill listed in `opencode.json` instructions array must be referenced by at least one agent prompt. No dead skills allowed.
4. **Input/output contracts** — the OUTPUT FORMAT of agent A must match the INPUT CONTRACT of agent B
5. **Operator bridge** — operator.txt must have explicit handoff rules for every agent pair

Quick verification:
```bash
# Count skills in config vs referenced in agents
echo "Config:" && jq -r '.instructions[]' .opencode/opencode.json | grep skills/ | wc -l
echo "Referenced:" && grep -roh 'skills/[a-z-]*/SKILL.md\|[a-z-]*-testing\|[a-z-]*-fuzzing\|[a-z-]*-recon\|[a-z-]*-analysis\|[a-z-]*-enumeration\|[a-z-]*-logic\|[a-z-]*-dispatching\|[a-z-]*-generation' .opencode/prompts/agents/ | sort -u | wc -l
```

## Commit Conventions

- Always push to `dev` branch
- Git user: NeoTheCapt / usualwyy@163.com
- No Co-Authored-By headers
- No personal paths (/Users/cis/...) in committed code
- No API keys, tokens, or company names (OKX/OKG) in code
