# Command: Auth Configuration

You are the operator managing authentication credentials for the current engagement. The user's arguments specify the auth type and value.

## Step 1: Locate Active Engagement

Find the most recent engagement directory under `engagements/`:

```bash
source scripts/lib/engagement.sh
resolve_engagement_dir "$(pwd)"
```

If no engagement directory exists, inform the user to run `/engage` first and stop.

## Step 2: Parse Arguments

Read the user's arguments appended below this template. Expect one of:
- `cookie "session=abc; token=xyz"` — set cookie-based authentication
- `header "Authorization: Bearer ..."` — set header-based authentication
- `show` — display current auth.json contents
- `clear` — delete auth.json entirely

If no arguments are provided, default to `show`.

## Action: cookie

1. Read the existing auth.json if it exists:
   ```bash
   cat "<engagement_dir>/auth.json" 2>/dev/null || echo "{}"
   ```

2. Parse the cookie string from the user's arguments. The value is the quoted string after `cookie`.

3. Parse the cookie string into a JSON dict (e.g., `session=abc; token=xyz` becomes `{"session":"abc","token":"xyz"}`). Then merge the new cookies into the existing auth.json. Use bash to write:
   ```bash
   # Parse cookie string into JSON dict
   COOKIE_JSON=$(echo "<cookie string>" | tr ';' '\n' | sed 's/^ *//' | awk -F'=' '{
     key=$1; val=""; for(i=2;i<=NF;i++){if(i>2)val=val"=";val=val $i}
     if(key!="") printf "%s\t%s\n", key, val
   }' | jq -Rn '[inputs | split("\t") | {(.[0]): (.[1] // "")}] | add // {}')

   # Merge into existing auth.json
   EXISTING=$(cat "<engagement_dir>/auth.json" 2>/dev/null || echo '{}')
   echo "$EXISTING" | jq --argjson cookies "$COOKIE_JSON" '. * {"cookies": ((.cookies // {}) + $cookies)}' > "<engagement_dir>/auth.json"
   ```

4. Confirm what was saved. Display the updated auth.json contents.
5. Remind the user/operator: in-scope `run_tool curl` requests automatically read `auth.json` via `rtcurl`. Do not manually duplicate the same cookie in every request unless testing override behavior.

## Action: header

1. Read the existing auth.json if it exists:
   ```bash
   cat "<engagement_dir>/auth.json" 2>/dev/null || echo "{}"
   ```

2. Parse the header string from the user's arguments. The value is the quoted string after `header`. Split on the first `:` to get header name and value.

3. Merge the new header into the existing auth.json without overwriting unrelated cookies or headers:
   ```bash
   EXISTING=$(cat "<engagement_dir>/auth.json" 2>/dev/null || echo '{}')
   HEADER_NAME="<Header-Name>"
   HEADER_VALUE="<header value>"
   echo "$EXISTING" | jq --arg name "$HEADER_NAME" --arg value "$HEADER_VALUE" '
     . * {"headers": ((.headers // {}) + {($name): $value})}
   ' > "<engagement_dir>/auth.json"
   ```

4. Confirm what was saved. Display the updated auth.json contents.
5. Remind the user/operator: in-scope `run_tool curl` requests automatically read `auth.json` via `rtcurl`. Do not manually duplicate the same header in every request unless testing override behavior.

## Action: show

1. Read and display the contents of auth.json:
   ```bash
   cat "<engagement_dir>/auth.json" 2>/dev/null
   ```

2. If the file does not exist, inform the user that no auth credentials are configured.

## Action: clear

1. Remove the auth.json file:
   ```bash
   rm -f "<engagement_dir>/auth.json"
   ```

2. Confirm that auth credentials have been cleared.

## Post-Auth Re-Collection

After successfully configuring auth (cookie or header), if an active engagement exists
and Katana was previously running (check for scans/katana_output.jsonl):

1. Announce: "[operator] Auth configured. Re-crawling with credentials to discover authenticated endpoints."
2. Restart Katana with updated auth from `auth.json`:
   ```bash
   source scripts/lib/container.sh
   export ENGAGEMENT_DIR="<engagement_dir>"
   stop_katana
   start_katana "$(jq -r .target <engagement_dir>/scope.json)"
   ```
3. `start_katana` reads both `cookies` and `headers` from `auth.json`, so authenticated re-collection applies to either auth style.
4. In-scope `run_tool curl` requests also consume `auth.json` automatically via the engagement-scoped `rtcurl` wrapper.
5. New authenticated endpoints will flow into cases.db (dedup handles overlap with existing cases)
6. Resume the consumption loop for any new pending cases

## User Arguments

The auth type, value, and any additional context from the user follows:
