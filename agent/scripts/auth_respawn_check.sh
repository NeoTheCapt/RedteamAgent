#!/usr/bin/env bash
set -euo pipefail

# auth_respawn_check.sh — detect newly validated credentials and signal
# the operator to re-dispatch recon-specialist with the new auth context.
#
# Without this, the credential-auto-use rule in operator-core.md is just
# advisory text; the operator can land an auth foothold and forget to
# re-recon under the new identity. This helper does the diff mechanically:
#   - reads auth.json validated_credentials count
#   - compares to .auth-respawn-state.json (previous count)
#   - if new credentials appeared, touches .auth-respawn-required flag
#
# Operator turn loop should:
#   1. ./scripts/auth_respawn_check.sh "$DIR"
#   2. if [[ -f "$DIR/.auth-respawn-required" ]]; then
#        dispatch recon-specialist + source-analyzer with auth context
#        rm "$DIR/.auth-respawn-required"
#      fi
#
# Idempotent. Fails open on missing files (returns 0, no flag).

ENG_DIR="${1:?usage: auth_respawn_check.sh <engagement_dir>}"
AUTH_JSON="$ENG_DIR/auth.json"
STATE_FILE="$ENG_DIR/.auth-respawn-state.json"
FLAG_FILE="$ENG_DIR/.auth-respawn-required"

if [[ ! -f "$AUTH_JSON" ]]; then
    exit 0
fi

# Count validated_credentials. Fall through to 0 if jq parse fails.
current_count=$(jq '(.validated_credentials // []) | length' "$AUTH_JSON" 2>/dev/null || echo 0)
current_count=${current_count:-0}

prev_count=0
if [[ -f "$STATE_FILE" ]]; then
    prev_count=$(jq '.last_validated_count // 0' "$STATE_FILE" 2>/dev/null || echo 0)
    prev_count=${prev_count:-0}
fi

if (( current_count > prev_count )); then
    new_credentials=$((current_count - prev_count))
    {
        echo "[auth-respawn] $(date -u +%Y-%m-%dT%H:%M:%SZ) detected $new_credentials new validated credential(s)"
        echo "[auth-respawn] previous=$prev_count  current=$current_count"
        echo "[auth-respawn] operator should re-dispatch recon-specialist with new auth context"
    } > "$FLAG_FILE"
    echo "auth-respawn flag written: $FLAG_FILE" >&2
fi

# Update state. NEVER lower last_validated_count: if the operator
# manually removed a credential (current < previous), preserve the
# high-water mark so the next genuine increase from the lower count
# doesn't cause a phantom respawn for credentials we already saw.
new_state_count=$prev_count
if (( current_count > prev_count )); then
    new_state_count=$current_count
fi
jq -n --argjson n "$new_state_count" \
    --argjson cur "$current_count" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{last_validated_count: $n, current_count_observed: $cur, updated_at: $ts}' > "$STATE_FILE"
