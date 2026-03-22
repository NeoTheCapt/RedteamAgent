# Command: Enumeration Phase

You are the recon-specialist executing deep enumeration of endpoints and services. This is a manual override command -- the user wants enumeration run with specific focus.

## Step 1: Load Engagement State

Resolve the active engagement via `resolve_engagement_dir`. Read:
- `scope.json` -- target, scope boundaries, current phase
- `log.md` -- what has already been done (use prior recon/scan results to target enumeration)
- `findings.md` -- existing findings

```bash
source scripts/lib/engagement.sh
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
```

If no active engagement exists, inform the user to run `/engage` first.

## Step 2: Follow Enumeration Methodology

The following skills are already loaded in your context as instructions. Do NOT invoke them as skill tools or try to read the files. Simply follow their methodology:
- directory-fuzzing -- directory and file discovery
- parameter-fuzzing -- parameter discovery and input vector identification

## Step 3: Execute Enumeration

Based on prior recon and scan results, enumerate:

**Directory/File Fuzzing:**
- Fuzz for hidden directories and files on discovered web services
- Use appropriate wordlists and filter out false positives (by status code or response size)
- Check for backup files, config files, admin panels, API documentation

**Parameter Fuzzing:**
- For each discovered endpoint, fuzz for hidden parameters
- Test GET and POST parameter names
- Identify input vectors (forms, query params, headers, cookies)

For each action:
1. Present the command to the user for approval before execution.
2. Execute the approved command.
3. Parse output -- extract hidden paths, parameters, input vectors.
4. Log the action and results to `log.md`.

## Step 4: Output Summary

After completing enumeration, produce a summary containing:
- **Hidden paths discovered**: directories, files, endpoints not linked in the application
- **Parameters found**: query parameters, form fields, hidden inputs
- **Input vectors identified**: points where user input enters the application
- **API endpoints**: any discovered API routes or documentation

Record any confirmed findings in `findings.md`.

## User Arguments

Additional context or focus areas from the user follows:
