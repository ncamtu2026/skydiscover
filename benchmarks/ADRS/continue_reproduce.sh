#!/usr/bin/env bash
# Global continue launcher — resume all benchmarks from their latest checkpoint.
# Add/remove lines below to control which benchmarks to continue.
set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"

# ── Benchmarks to continue (comment out to skip) ─────────────────────────────

bash "$SCRIPT_DIR/cloudcast/reproduce/continue_reproduce.sh"      &
bash "$SCRIPT_DIR/llm_sql/reproduce/continue_reproduce.sh"        &
bash "$SCRIPT_DIR/txn_scheduling/reproduce/continue_reproduce.sh" &

# bash "$SCRIPT_DIR/eplb/reproduce/continue_reproduce.sh"          &
# bash "$SCRIPT_DIR/prism/reproduce/continue_reproduce.sh"         &

# ─────────────────────────────────────────────────────────────────────────────

wait
echo "continue_reproduce.sh: all benchmarks finished."
