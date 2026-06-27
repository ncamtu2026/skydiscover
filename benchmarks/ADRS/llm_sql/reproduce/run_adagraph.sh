#!/usr/bin/env bash
# LLM SQL — AdaGraph: AdaEvolve's adaptive machinery over the ExperienceGraph
# (problem_view nodes are the islands). RUNS=N parallel runs (default 1).
# Override MODEL / API_BASE / ITERATIONS via env.
set -euo pipefail

MODEL="${MODEL:-glm-4.7}"
API_BASE="${API_BASE:-https://api.int2.net/v1}"
ITERATIONS="${ITERATIONS:-100}"
RUNS="${RUNS:-1}"

cd "$(dirname "$0")/.."

run() {
  local ts
  ts=$(date +%m%d_%H%M%S)
  echo "== llm_sql / adagraph / $ts =="
  uv run skydiscover-run initial_program.py evaluator/evaluator.py \
    -c reproduce/config_adagraph.yaml \
    -s adagraph -m "$MODEL" --api-base "$API_BASE" -i "$ITERATIONS" \
    -o "outputs/reproduce/adagraph/adagraph_${ts}"
}

for i in $(seq 1 "$RUNS"); do
  [[ "$i" -gt 1 ]] && sleep 5
  run &
done

wait
echo "llm_sql adagraph: finished."
