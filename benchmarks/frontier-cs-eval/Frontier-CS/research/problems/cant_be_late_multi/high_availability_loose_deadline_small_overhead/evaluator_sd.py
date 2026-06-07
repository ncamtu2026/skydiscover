"""Skydiscover-compatible evaluator for cant_be_late_multi / high_availability_loose_deadline_small_overhead.

Delegates entirely to Frontier-CS ResearchDockerRunner so Docker handles
dependency installation, dataset setup, and evaluation identically to the
official evaluation pipeline.
"""
from pathlib import Path

from frontier_cs.runner.research_docker import ResearchDockerRunner

_FRONTIER_BASE = Path(__file__).parents[4]  # .../Frontier-CS/
_DATASETS_DIR  = _FRONTIER_BASE / "research" / "datasets"
_PROBLEM_ID    = "cant_be_late_multi/high_availability_loose_deadline_small_overhead"

_runner = ResearchDockerRunner(
    base_dir=_FRONTIER_BASE,
    datasets_dir=_DATASETS_DIR,
    timeout=900,
)


def evaluate(program_path: str) -> dict:
    code = Path(program_path).read_text(encoding="utf-8")
    result = _runner.evaluate(_PROBLEM_ID, code)
    return {
        "combined_score": result.score if result.score is not None else 0.0,
        "runs_successfully": 1.0 if result.success else 0.0,
        "duration_seconds": result.duration_seconds or 0.0,
        "status": result.status.value,
        "error": result.message if not result.success else None,
    }
