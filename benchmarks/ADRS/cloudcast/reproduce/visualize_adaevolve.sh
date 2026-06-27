#!/usr/bin/env bash
# Visualize an AdaEvolve run by replaying its checkpoints into the live monitor
# dashboard (timeline of programs by score). AdaEvolve has no ExperienceGraph tree,
# so this uses the checkpoint viewer rather than the EG visualizer.
#
# Env vars:
#   RUN       — specific run dir to view (default: latest under outputs/reproduce/adaevolve/)
#   PORT      — port for the dashboard server (default: 8765)
#   SUMMARY   — set to 1 to enable per-program LLM summaries via the glm endpoint
set -euo pipefail

PORT="${PORT:-8765}"
SUMMARY="${SUMMARY:-0}"

cd "$(dirname "$0")/.."

RUN="${RUN:-$(ls -d outputs/reproduce/adaevolve/adaevolve_* 2>/dev/null | sort -r | head -1)}"

if [[ -z "$RUN" || ! -d "$RUN" ]]; then
  echo "No adaevolve runs found under outputs/reproduce/adaevolve/"
  echo "Run 'bash reproduce/run_adaevolve.sh' first."
  exit 1
fi

echo "Visualizing run: $RUN"
echo "Dashboard: http://localhost:${PORT}/"
echo ""

summary_args=()
if [[ "$SUMMARY" == "1" ]]; then
  # Per-program LLM summaries via the glm endpoint (one LLM call per program).
  summary_args=(--summary-model "glm-4.7" --summary-api-base "https://api.int2.net/v1")
fi
# Otherwise the viewer only auto-summarises if OPENAI_API_KEY is set (gpt-5-mini).

uv run python -m skydiscover.extras.monitor.viewer "$RUN" \
  --port "$PORT" "${summary_args[@]}"
