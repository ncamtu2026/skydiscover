#!/usr/bin/env bash
# CloudCast — AdaEvolve: adaptive multi-island evolution (baseline to compare vs GraphEvolve).
# RUNS=N runs (default 1). Set SEQUENTIAL=1 to run one after another instead of in parallel.
# Override MODEL / API_BASE / ITERATIONS via env.
set -euo pipefail

ITERATIONS="${ITERATIONS:-100}"
RUNS="${RUNS:-1}"
SEQUENTIAL="${SEQUENTIAL:-0}"

cd "$(dirname "$0")/.."

run() {
  local ts extra_args=()
  ts=$(date +%m%d_%H%M%S)
  # Model and api_base come from config by default; override via env if set.
  [[ -n "${MODEL:-}" ]]    && extra_args+=(-m "$MODEL")
  [[ -n "${API_BASE:-}" ]] && extra_args+=(--api-base "$API_BASE")
  echo "== cloudcast / adaevolve / $ts =="
  uv run skydiscover-run initial_program.py evaluator/evaluator.py \
    -c reproduce/adaevolve/config_adaevolve.yaml \
    -s adaevolve -i "$ITERATIONS" \
    "${extra_args[@]}" \
    -o "outputs/reproduce/adaevolve/adaevolve_${ts}"
}

for i in $(seq 1 "$RUNS"); do
  if [[ "$SEQUENTIAL" == "1" ]]; then
    echo ">> Run $i / $RUNS"
    run
  else
    [[ "$i" -gt 1 ]] && sleep 5
    run &
  fi
done

[[ "$SEQUENTIAL" != "1" ]] && wait
echo "cloudcast adaevolve: finished."
