"""
KnowledgeEvolve — standalone RAG module for injecting paper knowledge
into optimization context.

Usage:
    ke = KnowledgeEvolve(config, embedder, llm_pool)
    context_str = await ke.get_context(...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from skydiscover.knowledge.config import KnowledgeEvolveConfig
from skydiscover.knowledge.embedder import BaseEmbedder
from skydiscover.knowledge.retriever import Retriever
from skydiscover.llm.llm_pool import LLMPool

logger = logging.getLogger(__name__)

_LEVEL_LABELS = {
    "L1": "Paradigm-level (broad, diverse — breakthrough ideas)",
    "L2": "Exploration (moderate — diverse techniques)",
    "L3": "Exploitation (specific — targeted optimizations)",
}

_DIGEST_SYSTEM = """\
You are a research assistant distilling academic paper knowledge into actionable insights.
Given retrieved paper excerpts, produce 3-5 concise bullet points.
Focus on concrete techniques or ideas that could directly improve the current optimization solution.
Be specific. Reference the paper content explicitly.
"""

_DIGEST_USER = """\
## Optimization task
{task_description}

## Search level: {level_label}

## Retrieved paper excerpts
{excerpts}

Summarize the most actionable insights as 3-5 bullet points.
"""


class KnowledgeEvolve:
    """
    Retrieves relevant paper knowledge and returns a formatted string
    suitable for injection into an LLM optimization prompt.

    This module is search-algorithm-agnostic. Integration flags (e.g.
    use_in_parent, use_in_paradigm) live in the caller's config.
    """

    def __init__(self, config: KnowledgeEvolveConfig, embedder: BaseEmbedder, llm_pool: LLMPool):
        self.config = config
        self.llm_pool = llm_pool
        self.retriever = Retriever(config, embedder, llm_pool)
        self.last_results: List[Dict] = []

    @staticmethod
    def _determine_level(stage: str, search_mode: Optional[str]) -> str:
        """Map (stage, mode) to retrieval level L1/L2/L3."""
        if stage == "paradigm":
            return "L1"
        if search_mode == "exploitation":
            return "L3"
        return "L2"  # exploration, balanced, or unknown

    async def get_context(
        self,
        task_description: str,
        current_best_score: float = 0.0,
        evaluator_feedback: Optional[str] = None,
        stage: str = "parent",
        search_mode: Optional[str] = None,
        parent_code: Optional[str] = None,
        parent_metrics: Optional[Dict[str, Any]] = None,
        failed_paradigms: Optional[List[str]] = None,
    ) -> str:
        """
        Retrieve relevant paper knowledge and return a formatted string.

        Args:
            task_description: System message / problem description.
            current_best_score: Best score seen so far.
            evaluator_feedback: Diagnostic text from the evaluator, if any.
            stage: "parent" | "paradigm" — determines retrieval level.
            search_mode: "exploration" | "exploitation" | "balanced" | None.
            parent_code: Current parent solution code (used for L2/L3 queries).
            parent_metrics: Parent metrics dict (used for L3 queries).
            failed_paradigms: Previously tried paradigm descriptions (L1 only).

        Returns:
            Formatted knowledge context string, or "" if nothing retrieved.
        """
        level = self._determine_level(stage, search_mode)

        results = await self.retriever.retrieve(
            task_description=task_description,
            current_best_score=current_best_score,
            evaluator_feedback=evaluator_feedback,
            level=level,
            parent_code=parent_code,
            parent_metrics=parent_metrics,
            failed_paradigms=failed_paradigms,
        )

        self.last_results = results
        if not results:
            logger.info(f"KnowledgeEvolve [{level}|{stage}]: no results retrieved")
            return ""

        titles = [r.get("metadata", {}).get("title", "?")[:50] for r in results]
        logger.info(
            f"KnowledgeEvolve [{level}|{stage}]: retrieved {len(results)} docs — "
            + ", ".join(f'"{t}"' for t in titles[:3])
            + (" ..." if len(results) > 3 else "")
        )

        if self.config.output_mode == "digest":
            return await self._digest(results, task_description, level)
        return self._format_raw(results)

    def _format_raw(self, results: List[Dict]) -> str:
        lines = [
            "## KNOWLEDGE REFERENCES",
            "Excerpts from academic papers that may provide relevant techniques or insights.",
            "Use them as inspiration where applicable.\n",
        ]
        for i, result in enumerate(results, 1):
            meta = result.get("metadata", {})
            field_type = meta.get("field_type", "unknown")
            title = meta.get("title", "Unknown paper")
            content = result.get("document", "")

            if self.config.max_tokens_per_sample:
                char_limit = self.config.max_tokens_per_sample * 4  # ~4 chars/token
                if len(content) > char_limit:
                    content = content[:char_limit] + "\n... (truncated)"

            lines.append(f"### [{i}] {title} — {field_type}")
            lines.append(content)
            lines.append("")

        lines.append(
            "## ATTRIBUTION REQUIRED\n"
            "After writing your solution, add exactly ONE comment line at the very end of the code block:\n"
            "  # KNOWLEDGE_ATTRIBUTION: <your attribution>\n"
            "Rules:\n"
            "- If any paper above motivated or inspired your solution, cite it by [N] and title, "
            "then briefly explain what concept or technique you borrowed and how you applied it.\n"
            "  Example: # KNOWLEDGE_ATTRIBUTION: [2] DeDe — adapted its resource-partitioning heuristic "
            "to split broadcast tree per cloud; [5] Caribou — borrowed geo-routing cost model for link selection\n"
            "- If none of the papers influenced your solution, write: # KNOWLEDGE_ATTRIBUTION: none\n"
            "Do NOT skip this line."
        )

        return "\n".join(lines)

    async def _digest(
        self, results: List[Dict], task_description: str, level: str
    ) -> str:
        """Compress retrieved results into actionable bullet points via LLM."""
        excerpts_parts = []
        for i, result in enumerate(results, 1):
            meta = result.get("metadata", {})
            title = meta.get("title", "Unknown")
            field_type = meta.get("field_type", "")
            content = result.get("document", "")[:600]
            excerpts_parts.append(f"[{i}] {title} ({field_type}):\n{content}")

        try:
            response = await self.llm_pool.generate(
                system_message=_DIGEST_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": _DIGEST_USER.format(
                        task_description=task_description[:500],
                        level_label=_LEVEL_LABELS[level],
                        excerpts="\n\n".join(excerpts_parts),
                    ),
                }],
                temperature=0.5,
                max_tokens=1200,
                reasoning_effort=None,
            )
            digest = response.text or ""
            return "## KNOWLEDGE INSIGHTS\n\n" + digest
        except Exception as e:
            logger.warning(f"Digest LLM call failed ({e}), falling back to raw format.")
            return self._format_raw(results)
