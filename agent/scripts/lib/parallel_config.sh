#!/usr/bin/env bash
# Parallel dispatch configuration.
# Override any value via environment variable.

# --- Consume-test parallelism ---
REDTEAM_MAX_PARALLEL_BATCHES="${REDTEAM_MAX_PARALLEL_BATCHES:-3}"
REDTEAM_MAX_SAME_AGENT="${REDTEAM_MAX_SAME_AGENT:-2}"
REDTEAM_BATCH_SIZE="${REDTEAM_BATCH_SIZE:-5}"

# --- Phase-level parallelism ---
REDTEAM_RECON_PARALLEL="${REDTEAM_RECON_PARALLEL:-2}"
REDTEAM_EXPLOIT_PARALLEL="${REDTEAM_EXPLOIT_PARALLEL:-2}"

# --- Timeouts ---
REDTEAM_SUBAGENT_TIMEOUT="${REDTEAM_SUBAGENT_TIMEOUT:-300}"
