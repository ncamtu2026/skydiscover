#!/usr/bin/env bash
# CloudCast ablation study.
# Sections: (1) knowledge-evolve cases, (2) experience-graph (memory) cases.
# RUNS=N  — start N parallel runs per case (default 1).
# sleep 5s before each subsequent background job to stagger API calls.
set -euo pipefail

MODEL="${MODEL:-glm-4.7}"
API_BASE="${API_BASE:-https://api.int2.net/v1}"
ITERATIONS="${ITERATIONS:-100}"
RUNS="${RUNS:-1}"

cd "$(dirname "$0")/.."

run() {
  local case=$1 cfg=$2 section=$3
  local ts=$(date +%m%d_%H%M%S)
  echo "== cloudcast / $section/$case / $ts =="
  uv run skydiscover-run initial_program.py evaluator/evaluator.py \
    -c "reproduce/$cfg" \
    -s adaevolve -m "$MODEL" --api-base "$API_BASE" -i "$ITERATIONS" \
    -o "outputs/reproduce/${section}/${case}_${ts}"
}

# ---------------------------------------------------------------------------
# Knowledge-evolve cases (comment/uncomment as needed)
# ---------------------------------------------------------------------------
# for i in $(seq 1 "$RUNS"); do
#   [[ "$i" -gt 1 ]] && sleep 5
#   run ke_paradigm knowledge/config_ke_paradigm.yaml knowledge &
#   sleep 5
#   run ke_both     knowledge/config_ke_both.yaml     knowledge &
# done
# wait
# echo "cloudcast reproduce: knowledge cases finished."

# ---------------------------------------------------------------------------
# Experience-graph (memory) cases
# ---------------------------------------------------------------------------
for i in $(seq 1 "$RUNS"); do
  [[ "$i" -gt 1 ]] && sleep 5
  run eg_only     memory/config_eg_only.yaml     memory &
  sleep 5
  run eg_paradigm memory/config_eg_paradigm.yaml memory &
done

wait
echo "cloudcast reproduce: memory cases finished."
