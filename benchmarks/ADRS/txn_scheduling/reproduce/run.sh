#!/usr/bin/env bash
# Transaction Scheduling knowledge-evolve ablation study.
# Runs 4 cases in parallel: no KE, KE paradigm-only, KE parent-only, KE both.
set -euo pipefail

MODEL="${MODEL:-glm-4.7}"
API_BASE="${API_BASE:-https://api.int2.net/v1}"
ITERATIONS="${ITERATIONS:-100}"
TS=$(date +%m%d_%H%M%S)

cd "$(dirname "$0")/.."

run() {
  local case=$1 cfg=$2
  echo "== txn_scheduling / $case / $TS =="
  uv run skydiscover-run initial_program.py evaluator/evaluator.py \
    -c "reproduce/$cfg" \
    -s adaevolve -m "$MODEL" --api-base "$API_BASE" -i "$ITERATIONS" \
    -o "outputs/reproduce/${case}_${TS}"
}

run no_ke         config_no_ke.yaml       &
run ke_paradigm   config_ke_paradigm.yaml &
run ke_parent     config_ke_parent.yaml   &
run ke_both       config_ke_both.yaml     &

wait
echo "txn_scheduling reproduce: all 4 cases finished."
