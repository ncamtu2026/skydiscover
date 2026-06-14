#!/usr/bin/env bash
# CloudCast — resume ablation cases from their latest checkpoints.
# Sections: (1) knowledge-evolve cases, (2) experience-graph (memory) cases.
# N_CONTINUE=N  — resume the N most recent runs per case (default 1).
# sleep 5s before each subsequent background job to stagger API calls.
set -euo pipefail

MODEL="${MODEL:-glm-4.7}"
API_BASE="${API_BASE:-https://api.int2.net/v1}"
ITERATIONS="${ITERATIONS:-100}"
N_CONTINUE="${N_CONTINUE:-1}"

cd "$(dirname "$0")/.."

# Resume up to N_CONTINUE most-recent runs for a given case.
# Starts each as a background job; sleeps 5s between consecutive starts.
continue_n_cases() {
  local case=$1 cfg=$2 section=$3
  local count=0
  while IFS= read -r run_dir; do
    local ckpt
    ckpt=$(ls -d "$run_dir/checkpoints/checkpoint_"* 2>/dev/null | sort -V | tail -1)
    if [[ -n "$ckpt" ]]; then
      [[ "$count" -gt 0 ]] && sleep 5
      echo "== cloudcast / $section/$case: resuming ${ckpt##*/} → $run_dir =="
      uv run skydiscover-run initial_program.py evaluator/evaluator.py \
        -c "reproduce/$cfg" \
        -s adaevolve -m "$MODEL" --api-base "$API_BASE" -i "$ITERATIONS" \
        --checkpoint "$ckpt" \
        --output "$run_dir" &
      count=$((count + 1))
      [[ "$count" -ge "$N_CONTINUE" ]] && break
    fi
  done < <(ls -d "outputs/reproduce/${section}/${case}_"* 2>/dev/null | sort -r)
  [[ "$count" -eq 0 ]] && echo "== cloudcast / $section/$case: no checkpoints found, skipping =="
}

# ---------------------------------------------------------------------------
# Knowledge-evolve cases (comment/uncomment as needed)
# ---------------------------------------------------------------------------
# continue_n_cases ke_paradigm knowledge/config_ke_paradigm.yaml knowledge
# sleep 5
# continue_n_cases ke_both     knowledge/config_ke_both.yaml     knowledge
# wait
# echo "cloudcast continue_reproduce: knowledge cases finished."

# ---------------------------------------------------------------------------
# Experience-graph (memory) cases
# ---------------------------------------------------------------------------
continue_n_cases eg_only     memory/config_eg_only.yaml     memory
sleep 5
continue_n_cases eg_paradigm memory/config_eg_paradigm.yaml memory

wait
echo "cloudcast continue_reproduce: memory cases finished."
