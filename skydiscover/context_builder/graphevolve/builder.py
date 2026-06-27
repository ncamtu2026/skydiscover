"""GraphEvolve context builder.

Extends :class:`DefaultContextBuilder` with three action-specific prompts —
``mutate`` (exploit), ``crossover`` and ``space_explore`` — that mirror the
layout and placeholders of the AdaEvolve full-rewrite template.  All prompt text
is in English; only the project docs are in Vietnamese.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from skydiscover.config import Config
from skydiscover.context_builder.default import DefaultContextBuilder
from skydiscover.context_builder.utils import TemplateManager, prog_attr
from skydiscover.search.base_database import Program
from skydiscover.utils.code_utils import extract_evolve_block
from skydiscover.utils.metrics import compute_proxy_score

logger = logging.getLogger(__name__)


class GraphEvolveContextBuilder(DefaultContextBuilder):
    """Builds mutate / crossover / space-explore prompts for GraphEvolve."""

    def __init__(self, config: Config):
        super().__init__(config)
        default_templates = str(Path(__file__).parent.parent / "default" / "templates")
        graphevolve_templates = str(Path(__file__).parent / "templates")
        self.template_manager = TemplateManager(
            default_templates, graphevolve_templates, self.context_config.template_dir
        )

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _db_config(self) -> Any:
        return getattr(self.config.search, "database", None)

    @property
    def _evolve_block_only(self) -> bool:
        return bool(getattr(self._db_config(), "evolve_block_only", True))

    @property
    def _exploit_diff_based(self) -> bool:
        return bool(getattr(self._db_config(), "exploit_diff_based", True))

    def _prompt_solution(self, solution: Optional[str]) -> str:
        """The code shown to the LLM: only the EVOLVE block when enabled."""
        solution = solution or ""
        if not self._evolve_block_only:
            return solution
        return extract_evolve_block(solution)

    def _reduce_one(self, program: Optional[Program]) -> Optional[Program]:
        """Return a shallow copy whose .solution is reduced to the EVOLVE block."""
        if program is None or not self._evolve_block_only:
            return program
        full = prog_attr(program, "solution", "") or ""
        block = extract_evolve_block(full)
        if not block or block == full:
            return program
        clone = copy.copy(program)
        try:
            clone.solution = block
        except Exception:  # pragma: no cover - non-dataclass program
            return program
        return clone

    def _reduce(
        self, current_program: Union[Program, Dict[str, Program], None]
    ) -> Union[Program, Dict[str, Program], None]:
        if isinstance(current_program, dict):
            return {k: self._reduce_one(v) for k, v in current_program.items()}
        return self._reduce_one(current_program)

    # Reduce solutions to their EVOLVE block before the default renderer formats them.
    def _format_current_program(
        self, current_program: Union[Program, Dict[str, Program]], language: str
    ) -> str:
        return super()._format_current_program(self._reduce(current_program), language)

    def _format_single_context_program(
        self, program: Program, index: int, language: str, lines: list
    ) -> None:
        super()._format_single_context_program(
            self._reduce_one(program), index, language, lines
        )

    def _proxy(self, metrics: Dict[str, Any]) -> float:
        db = self._db_config()
        return compute_proxy_score(
            metrics or {},
            fitness_key=getattr(db, "fitness_key", None),
            pareto_objectives=getattr(db, "pareto_objectives", []) or [],
            higher_is_better=getattr(db, "higher_is_better", {}) or {},
        )

    def _timeout_warning(self) -> str:
        timeout = getattr(self.config.evaluator, "timeout", None)
        if not timeout:
            return ""
        return (
            f"- Time limit: Programs should complete execution within {timeout} seconds; "
            "otherwise, they will timeout."
        )

    def _task_objective(self) -> str:
        return "Improve the program to maximize its combined_score on the task evaluator."

    @property
    def _language(self) -> str:
        return self.config.language or "python"

    # ------------------------------------------------------------------
    # Section formatting
    # ------------------------------------------------------------------
    def format_previous_attempts_in_direction(
        self, parent: Program, siblings: List[Program]
    ) -> str:
        """Compact 'what was already tried in this direction' block.

        Mirrors AdaEvolve's sibling context: parent_fit -> leaf_fit (delta)
        [IMPROVED/REGRESSED/NO CHANGE] plus a one-line summary.
        """
        if not siblings:
            return "No previous attempts yet."

        parent_fit = self._proxy(prog_attr(parent, "metrics", {}) or {})
        improved = regressed = unchanged = 0
        entries: List[str] = []
        for i, child in enumerate(siblings, 1):
            child_fit = self._proxy(prog_attr(child, "metrics", {}) or {})
            delta = child_fit - parent_fit
            if delta > 1e-4:
                status, improved = "IMPROVED", improved + 1
            elif delta < -1e-4:
                status, regressed = "REGRESSED", regressed + 1
            else:
                status, unchanged = "NO CHANGE", unchanged + 1
            entries.append(f"  {i}. {parent_fit:.4f} -> {child_fit:.4f} ({delta:+.4f}) [{status}]")

        lines = [
            f"Summary: {improved} improved, {unchanged} unchanged, {regressed} regressed",
            *entries,
            "Avoid repeating approaches that did not work.",
        ]
        return "\n".join(lines)

    def _error_section(self, error_context: Optional[str]) -> str:
        if not error_context:
            return ""
        return (
            "## Previous Attempt Failed\n"
            f"The previous generation failed with:\n{error_context}\n"
            "Fix this issue directly rather than guessing.\n\n"
        )

    def _direction_guidance(
        self, direction_info: Optional[Dict[str, str]], error_context: Optional[str]
    ) -> str:
        sections: List[str] = []
        if direction_info:
            sections.append(
                "## Solution Direction\n"
                f"Problem view: {direction_info.get('pv_label', '')} — "
                f"{direction_info.get('pv_desc', '')}\n"
                f"Solution strategy: {direction_info.get('ss_label', '')} — "
                f"{direction_info.get('ss_desc', '')}\n"
                "Refine within this direction."
            )
        if error_context:
            sections.append(
                "## Previous Attempt Failed\n"
                f"The previous generation failed with:\n{error_context}\n"
                "Fix this issue directly rather than guessing."
            )
        return "\n\n".join(sections)

    def _format_sources(self, sources: List[Dict[str, Any]], language: str) -> str:
        lines: List[str] = []
        for i, src in enumerate(sources, 1):
            program = src["program"]
            label = src.get("label", "")
            desc = src.get("description", "")
            score = src.get("score")
            solution = self._prompt_solution(prog_attr(program, "solution", ""))
            score_str = f" (score: {score:.4f})" if isinstance(score, (int, float)) else ""
            lines.append(f"## Source {i}: {label}{score_str}")
            if desc:
                lines.append(f"Direction: {desc}")
            lines.append(f"```{language}\n{solution}\n```\n")
        return "\n".join(lines)

    def _space_instruction(
        self, target: str, best_pv_info: Optional[Dict[str, str]]
    ) -> str:
        if target == "new_form":
            return (
                "Introduce a fundamentally NEW way of framing the problem (a new problem view) "
                "that is not present in the explored map above. Do not reuse an existing framing."
            )
        pv_label = (best_pv_info or {}).get("pv_label", "the current best framing")
        pv_desc = (best_pv_info or {}).get("pv_desc", "")
        return (
            f"Keep the framing of the current best solution ({pv_label}: {pv_desc}), but pursue a "
            "NEW solution strategy under it that has not been tried yet."
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------
    def build_mutate_prompt(
        self,
        parent: Program,
        direction_info: Optional[Dict[str, str]] = None,
        siblings: Optional[List[Program]] = None,
        context_programs: Optional[List[Program]] = None,
        error_context: Optional[str] = None,
    ) -> Dict[str, str]:
        language = self._language
        metrics = prog_attr(parent, "metrics", {}) or {}
        other_ctx = (
            self._format_other_context_programs(
                {"Context Solutions (same direction)": context_programs or []}, language
            )
            if context_programs
            else ""
        )
        # EXPLOIT refines a single parent: use SEARCH/REPLACE diffs when enabled
        # (the fixed wrapper is preserved automatically), otherwise full rewrite.
        template_key = "mutate_diff" if self._exploit_diff_based else "mutate"
        user = self.template_manager.get_template(template_key).format(
            metrics=self._format_metrics(metrics),
            improvement_areas=self._identify_improvement_areas(
                prog_attr(parent, "solution", ""), metrics, []
            ),
            previous_attempts=self.format_previous_attempts_in_direction(parent, siblings or []),
            other_context_programs=other_ctx,
            current_program=self._format_current_program(parent, language),
            search_guidance=self._direction_guidance(direction_info, error_context),
            task_objective=self._task_objective(),
            language=language,
            timeout_warning=self._timeout_warning(),
        )
        return {"system": self._get_system_message(), "user": user}

    def _format_idea_guidance(
        self, idea: Optional[Dict[str, Any]], idea_type: str = "crossover"
    ) -> str:
        """Format a pre-generated idea dict into a prompt section (empty string if no idea)."""
        if not idea:
            return ""
        if idea_type == "crossover":
            lines = ["# Proposed Synthesis Plan (implement this — do not deviate)", ""]
            if idea.get("synthesis_strategy"):
                lines.append(f"Strategy: {idea['synthesis_strategy']}")
            if idea.get("key_ideas"):
                lines.append("Key ideas to combine:")
                for ki in idea["key_ideas"]:
                    lines.append(f"  - {ki}")
            if idea.get("combination_rationale"):
                lines.append(f"Rationale: {idea['combination_rationale']}")
            if idea.get("what_to_avoid"):
                lines.append(f"Avoid: {idea['what_to_avoid']}")
            if idea.get("expected_strength"):
                lines.append(f"Expected strength: {idea['expected_strength']}")
        else:  # space_explore
            lines = ["# Proposed Exploration Direction (implement this — do not deviate)", ""]
            if idea.get("approach_name"):
                lines.append(f"New approach: {idea['approach_name']}")
            if idea.get("problem_framing"):
                lines.append(f"Problem framing: {idea['problem_framing']}")
            if idea.get("solution_strategy"):
                lines.append(f"Solution strategy: {idea['solution_strategy']}")
            if idea.get("why_different"):
                lines.append(f"Why different: {idea['why_different']}")
            if idea.get("key_mechanisms"):
                lines.append("Key mechanisms:")
                for m in idea["key_mechanisms"]:
                    lines.append(f"  - {m}")
            if idea.get("expected_advantage"):
                lines.append(f"Expected advantage: {idea['expected_advantage']}")
        return "\n".join(lines) + "\n"

    def build_crossover_prompt(
        self,
        sources: List[Dict[str, Any]],
        previous_attempts: Optional[List[Program]] = None,
        idea: Optional[Dict[str, Any]] = None,
        error_context: Optional[str] = None,
    ) -> Dict[str, str]:
        language = self._language
        prev_text = self._format_previous_crossovers(previous_attempts or [], language)
        user = self.template_manager.get_template("crossover").format(
            source_solutions=self._format_sources(sources, language),
            previous_crossover_attempts=prev_text,
            error_section=self._error_section(error_context),
            idea_guidance=self._format_idea_guidance(idea, "crossover"),
            task_objective=self._task_objective(),
            language=language,
            timeout_warning=self._timeout_warning(),
        )
        return {"system": self._get_system_message(), "user": user}

    def _format_previous_crossovers(self, attempts: List[Program], language: str) -> str:
        if not attempts:
            return "No previous crossover attempts yet."
        lines = [f"{len(attempts)} prior crossover(s) already tried (do not repeat them):"]
        for i, prog in enumerate(attempts, 1):
            score = self._proxy(prog_attr(prog, "metrics", {}) or {})
            sol = self._prompt_solution(prog_attr(prog, "solution", "") or "")
            # Show just a short snippet so the prompt doesn't bloat
            snippet = sol[:300].rstrip()
            if len(sol) > 300:
                snippet += "\n    # ... (truncated)"
            lines.append(f"\n### Prior crossover {i} (score: {score:.4f})")
            lines.append(f"```{language}\n{snippet}\n```")
        return "\n".join(lines)

    def build_space_prompt(
        self,
        target: str,
        explored_map: str,
        exemplars: Optional[List[Program]] = None,
        seed: Optional[Program] = None,
        best_pv_info: Optional[Dict[str, str]] = None,
        idea: Optional[Dict[str, Any]] = None,
        error_context: Optional[str] = None,
    ) -> Dict[str, str]:
        language = self._language
        exemplar_text = (
            self._format_other_context_programs(
                {"Reference Solutions": exemplars or []}, language
            )
            if exemplars
            else "(none)"
        )
        seed_text = self._format_current_program(seed, language) if seed else "(none)"
        user = self.template_manager.get_template("space_explore").format(
            explored_map=explored_map or "(empty)",
            exemplars=exemplar_text,
            seed=seed_text,
            error_section=self._error_section(error_context),
            idea_guidance=self._format_idea_guidance(idea, "space_explore"),
            space_instruction=self._space_instruction(target, best_pv_info),
            task_objective=self._task_objective(),
            language=language,
            timeout_warning=self._timeout_warning(),
        )
        return {"system": self._get_system_message(), "user": user}
