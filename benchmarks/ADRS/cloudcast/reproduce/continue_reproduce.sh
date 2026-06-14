#!/usr/bin/env bash
# CloudCast — resume all 4 KE ablation cases from their latest checkpoint.
set -euo pipefail

MODEL="${MODEL:-glm-4.7}"
API_BASE="${API_BASE:-https://api.int2.net/v1}"
ITERATIONS="${ITERATIONS:-100}"

cd "$(dirname "$0")/.."

# Find latest checkpoint under outputs/reproduce/<case>_*/checkpoints/
latest_checkpoint() {
  local case=$1
  local run_dir ckpt
  while IFS= read -r run_dir; do
    ckpt=$(ls -d "$run_dir/checkpoints/checkpoint_"* 2>/dev/null | sort -V | tail -1)
    [[ -n "$ckpt" ]] && { echo "$ckpt"; return; }
  done < <(ls -d "outputs/reproduce/${case}_"* 2>/dev/null | sort -r)
  echo ""
}

continue_case() {
  local case=$1 cfg=$2
  local ckpt run_dir
  ckpt=$(latest_checkpoint "$case")
  if [[ -z "$ckpt" ]]; then
    echo "== cloudcast / $case: no checkpoint found, skipping =="
    return
  fi
  # checkpoint path: outputs/reproduce/<run>/checkpoints/checkpoint_N
  # run_dir is the grandparent so new checkpoints go back into the same run folder
  run_dir=$(dirname "$(dirname "$ckpt")")
  echo "== cloudcast / $case: resuming from ${ckpt##*/} → output: $run_dir =="
  uv run skydiscover-run initial_program.py evaluator/evaluator.py \
    -c "reproduce/$cfg" \
    -s adaevolve -m "$MODEL" --api-base "$API_BASE" -i "$ITERATIONS" \
    --checkpoint "$ckpt" \
    --output "$run_dir"
}

continue_case no_ke         config_no_ke.yaml       &
# continue_case ke_paradigm   config_ke_paradigm.yaml &
continue_case ke_parent     config_ke_parent.yaml   &
# continue_case ke_both       config_ke_both.yaml     &

wait
echo "cloudcast continue_reproduce: all 4 cases finished."
