#!/usr/bin/env bash
# Global reproduce launcher — add/remove lines below to control which benchmarks run.
# Each benchmark's 4 KE ablation cases run in parallel within itself.
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"

# ── Fresh runs (comment out to skip) ─────────────────────────────────────────

bash "$SCRIPT_DIR/cloudcast/reproduce/run.sh"      &
bash "$SCRIPT_DIR/llm_sql/reproduce/run.sh"        &
bash "$SCRIPT_DIR/txn_scheduling/reproduce/run.sh" &

# bash "$SCRIPT_DIR/eplb/reproduce/run.sh"          &
# bash "$SCRIPT_DIR/prism/reproduce/run.sh"         &

# ─────────────────────────────────────────────────────────────────────────────

wait
echo "reproduce.sh: all benchmarks finished."
