#!/usr/bin/env bash
# Visualize LLM SQL AdaGraph runs. AdaGraph builds an ExperienceGraph
# (problem_view -> solution_strategy -> leaf), so this reuses the EG tree visualizer.
#
# Env vars:
#   LATEST    — how many latest runs to include (default: 1)
#   LIVE      — set to 1 to start the auto-refresh HTTP server
#   PORT      — port for the live server (default: 8765)
#   INTERVAL  — refresh interval in seconds (default: 5)
#   OUT       — override output HTML path (static mode only)
set -euo pipefail

LATEST="${LATEST:-1}"
LIVE="${LIVE:-0}"
PORT="${PORT:-8765}"
INTERVAL="${INTERVAL:-5}"

cd "$(dirname "$0")/.."

dirs=()
while IFS= read -r d; do
  dirs+=("$d")
done < <(ls -d outputs/reproduce/adagraph/adagraph_* 2>/dev/null | sort -r | head -"$LATEST")

if [[ ${#dirs[@]} -eq 0 ]]; then
  echo "No adagraph runs found under outputs/reproduce/adagraph/"
  echo "Run 'bash reproduce/run_adagraph.sh' first."
  exit 1
fi

echo "Found ${#dirs[@]} run(s):"
printf "  %s\n" "${dirs[@]}"
echo ""

if [[ "$LIVE" == "1" ]]; then
  echo "Starting live server on http://localhost:${PORT} (refresh every ${INTERVAL}s)"
  uv run python -m skydiscover.experience_graph.visualize "${dirs[@]}" \
    --live --port "$PORT" --interval "$INTERVAL"
else
  OUT="${OUT:-${dirs[0]}/experience_graph_viz.html}"
  uv run python -m skydiscover.experience_graph.visualize "${dirs[@]}" --out "$OUT"
  echo ""
  echo "Open: $OUT"
fi
