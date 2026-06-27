"""AdaGraph context builder.

Reuses :class:`AdaEvolveContextBuilder` for the normal exploit / migration prompts
and adds two structural prompts:

  - ``build_form_prompt``      → propose a genuinely NEW problem_view (framing).
  - ``build_direction_prompt`` → propose a NEW solution_strategy (direction) that is
    mechanistically distinct from the existing directions in a given problem_view.

Both can carry a paradigm idea and a distilled "what changed" insight block.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from skydiscover.context_builder.adaevolve.builder import AdaEvolveContextBuilder
from skydiscover.search.base_database import Program

_TPL_DIR = Path(__file__).parent / "templates"


class AdaGraphContextBuilder(AdaEvolveContextBuilder):
    """AdaEvolve context builder + form / direction prompts for AdaGraph."""

    def _wrap(self, base: str, paradigm: Optional[dict], insights: str) -> str:
        language = self.config.language or "python"
        sections: List[str] = []
        if paradigm:
            sections.append(self._format_paradigm_guidance(paradigm, language))
        if insights:
            sections.append(insights)
        if sections:
            return "\n\n".join(sections) + "\n\n" + base
        return base

    def build_form_prompt(
        self,
        explored_map: str,
        seed: Optional[Program],
        paradigm: Optional[dict] = None,
        insights: str = "",
    ) -> Dict[str, str]:
        """Ask for a fundamentally NEW framing (new problem_view)."""
        language = self.config.language or "python"
        seed_text = self._format_current_program(seed, language) if seed else "(none)"
        base = (_TPL_DIR / "form_reframe.txt").read_text().format(
            explored_map=explored_map or "(empty)",
            seed=seed_text,
            task_objective=self._task_objective_text(),
            language=language,
        )
        return {"system": self._get_system_message(), "user": self._wrap(base, paradigm, insights)}

    def build_direction_prompt(
        self,
        pv_info: Dict[str, str],
        sibling_directions: List[Dict[str, str]],
        seed: Optional[Program],
        paradigm: Optional[dict] = None,
        insights: str = "",
    ) -> Dict[str, str]:
        """Ask for a NEW direction (solution_strategy) within an existing framing,
        mechanistically distinct from the sibling directions."""
        language = self.config.language or "python"
        seed_text = self._format_current_program(seed, language) if seed else "(none)"
        existing = "\n".join(
            f"- {d.get('label', '')}: {(d.get('description') or '')[:140]}"
            for d in sibling_directions
        ) or "(no directions yet)"
        base = (_TPL_DIR / "direction.txt").read_text().format(
            pv_label=pv_info.get("label", ""),
            pv_description=pv_info.get("description", ""),
            existing_directions=existing,
            seed=seed_text,
            task_objective=self._task_objective_text(),
            language=language,
        )
        return {"system": self._get_system_message(), "user": self._wrap(base, paradigm, insights)}
