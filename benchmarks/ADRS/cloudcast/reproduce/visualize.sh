#!/usr/bin/env bash
# Generate ExperienceGraph visualization from run outputs.
# Single dir  → single-run interactive view.
# Multiple dirs → comparison view (overlaid timelines + tabbed trees).
# LIVE=1 → start auto-refresh HTTP server instead of writing a static file.
#
# Env vars:
#   SECTION   — subdir to scan: memory (default) or knowledge
#   LATEST    — how many latest runs per case to include (default: 1)
#   LIVE      — set to 1 to start live server
#   PORT      — port for live server (default: 8765)
#   INTERVAL  — refresh interval in seconds (default: 5)
#   OUT       — override output HTML path (static mode only)
set -euo pipefail

SECTION="${SECTION:-memory}"
LATEST="${LATEST:-1}"
LIVE="${LIVE:-0}"
PORT="${PORT:-8765}"
INTERVAL="${INTERVAL:-5}"

cd "$(dirname "$0")/.."

# Discover cases based on section
if [[ "$SECTION" == "memory" ]]; then
  CASES=(eg_only eg_paradigm)
else
  CASES=(ke_paradigm ke_both ke_parent no_ke)
fi

dirs=()
for case in "${CASES[@]}"; do
  while IFS= read -r d; do
    dirs+=("$d")
  done < <(ls -d "outputs/reproduce/${SECTION}/${case}_"* 2>/dev/null | sort -r | head -"$LATEST")
done

if [[ ${#dirs[@]} -eq 0 ]]; then
  echo "No output dirs found under outputs/reproduce/${SECTION}/"
  echo "Run 'bash reproduce/run.sh' first."
  exit 1
fi

echo "Found ${#dirs[@]} run(s):"
printf "  %s\n" "${dirs[@]}"
echo ""

if [[ "$LIVE" == "1" ]]; then
  echo "Starting live server on http://localhost:${PORT} (refresh every ${INTERVAL}s)"
  echo ""
  uv run python -m skydiscover.experience_graph.visualize "${dirs[@]}" \
    --live --port "$PORT" --interval "$INTERVAL"
else
  if [[ ${#dirs[@]} -eq 1 ]]; then
    OUT="${OUT:-${dirs[0]}/experience_graph_viz.html}"
  else
    TS=$(date +%m%d_%H%M%S)
    OUT="${OUT:-outputs/reproduce/${SECTION}/viz_comparison_${TS}.html}"
  fi
  uv run python -m skydiscover.experience_graph.visualize "${dirs[@]}" --out "$OUT"
  echo ""
  echo "Open: $OUT"
fi
